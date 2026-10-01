import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { GRAPH_CATALOG, GRAPH_NODE_KINDS, type GraphDefinition, type GraphNode, type GraphNodeKind, type GraphEdge, type GraphBindings } from '@/domain/workflowGraph'
import { WorkflowNode } from './WorkflowNode'
import { WorkflowInspector } from './WorkflowInspector'
import { bindingIssues, connectPort, removeNode, sourceKey, sourceLabel, TYPE_NAMES, updateNode, type WorkflowMaterial } from './graphEditorModel'
import './WorkflowEditor.css'

export interface WorkflowEditorIssue { message: string; nodeId?: string }
export interface WorkflowEditorProps {
  graph: GraphDefinition
  bindings: GraphBindings
  materials: WorkflowMaterial[]
  issues: WorkflowEditorIssue[]
  onChange: (graph: GraphDefinition) => void
  onBindingsChange: (bindings: GraphBindings) => void
  createNode: (kind: GraphNodeKind, graph: GraphDefinition) => GraphNode
  renderParameters: (node: GraphNode, onChange: (node: GraphNode) => void) => ReactNode
}
type Point = { x: number; y: number }
type Line = { id: string; path: string; type: string }

function autoPositions(graph: GraphDefinition, narrow: boolean): { points: Record<string, Point>; width: number; height: number } {
  if (narrow) return { points: Object.fromEntries([...graph.input_slots.map(slot => `slot:${slot.id}`), ...graph.nodes.map(node => node.id)].map((id, index) => [id, { x: 48, y: 30 + index * 235 }])), width: 302, height: Math.max(440, (graph.input_slots.length + graph.nodes.length) * 235 + 45) }
  const depth: Record<string, number> = Object.fromEntries(graph.nodes.map(node => [node.id, 1]))
  for (let pass = 0; pass < graph.nodes.length; pass++) {
    for (const edge of graph.edges) if (edge.source.kind === 'node') depth[edge.target.node_id] = Math.min(graph.nodes.length, Math.max(depth[edge.target.node_id] || 1, (depth[edge.source.node_id] || 1) + 1))
  }
  const layers: Record<number, string[]> = { 0: graph.input_slots.map(slot => `slot:${slot.id}`) }
  graph.nodes.forEach(node => { const layer = depth[node.id] || 1; (layers[layer] ||= []).push(node.id) })
  const maxCount = Math.max(2, ...Object.values(layers).map(items => items.length))
  const height = Math.max(520, maxCount * 235 + 45)
  const points: Record<string, Point> = {}
  for (const [layer, ids] of Object.entries(layers)) ids.forEach((id, index) => { points[id] = { x: 26 + Number(layer) * 262, y: 50 + index * 235 + (maxCount - ids.length) * 75 } })
  return { points, width: 26 + (Math.max(0, ...Object.values(depth)) + 1) * 262, height }
}

export default function WorkflowEditor({ graph, bindings, materials, issues, onChange, onBindingsChange, createNode, renderParameters }: WorkflowEditorProps) {
  const [selectedId, setSelectedId] = useState(graph.nodes[0]?.id || '')
  const [pendingSource, setPendingSource] = useState<GraphEdge['source'] | null>(null)
  const [error, setError] = useState('')
  const [narrow, setNarrow] = useState(() => window.innerWidth < 760)
  const [moved, setMoved] = useState<Record<string, Point>>({})
  const [lines, setLines] = useState<Line[]>([])
  const stageRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ id: string; x: number; y: number; origin: Point } | null>(null)
  const layout = autoPositions(graph, narrow)
  const positions = narrow ? layout.points : { ...layout.points, ...moved }
  const node = graph.nodes.find(item => item.id === selectedId)
  const materialIssues = bindingIssues(graph, bindings, materials)
  const allIssues = [...issues.map(issue => issue.message), ...materialIssues]
  useEffect(() => {
    const media = window.matchMedia('(max-width: 759px)')
    const change = () => setNarrow(media.matches)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  useEffect(() => { if (!graph.nodes.some(item => item.id === selectedId)) setSelectedId(graph.nodes[0]?.id || '') }, [graph.nodes, selectedId])
  useLayoutEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const measure = () => {
      const origin = stage.getBoundingClientRect()
      const endpoints = new Map(Array.from(stage.querySelectorAll<HTMLElement>('[data-endpoint]')).map(element => [element.dataset.endpoint, element]))
      setLines(graph.edges.flatMap((edge, index) => {
        const from = endpoints.get(`source:${sourceKey(edge.source)}`)
        const to = endpoints.get(`target:${edge.target.node_id}:${edge.target.port}`)
        if (!from || !to) return []
        const start = from.querySelector('.wg-port-dot')?.getBoundingClientRect() || from.getBoundingClientRect()
        const end = to.querySelector('.wg-port-dot')?.getBoundingClientRect() || to.getBoundingClientRect()
        const sx = start.left + start.width / 2 - origin.left; const sy = start.top + start.height / 2 - origin.top
        const tx = end.left + end.width / 2 - origin.left; const ty = end.top + end.height / 2 - origin.top
        const curve = narrow ? `M${sx},${sy} C${sx + 38},${sy + 42} ${tx - 38},${ty - 42} ${tx},${ty}` : `M${sx},${sy} C${sx + 64},${sy} ${tx - 64},${ty} ${tx},${ty}`
        return [{ id: String(index), path: curve, type: graph.input_slots.find(slot => edge.source.kind === 'slot' && slot.id === edge.source.slot_id)?.type || (edge.source.kind === 'node' && edge.source.port === 'audio' ? 'audio' : 'subtitle') }]
      }))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(stage)
    return () => observer.disconnect()
  }, [graph, bindings, narrow, moved])
  function connect(target: GraphEdge['target'], source: GraphEdge['source'] | null) {
    const result = connectPort(graph, target, source)
    setError(result.error)
    if (!result.error) { onChange(result.graph); setPendingSource(null) }
  }
  function moveStart(id: string, event: PointerEvent<HTMLElement>) {
    if (narrow || event.button !== 0) return
    dragRef.current = { id, x: event.clientX, y: event.clientY, origin: positions[id]! }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (!drag || narrow) return
    const x = Math.max(10, drag.origin.x + event.clientX - drag.x)
    const y = Math.max(12, drag.origin.y + event.clientY - drag.y)
    setMoved(current => ({ ...current, [drag.id]: { x, y } }))
  }
  function patchBinding(slotId: string, patch: Partial<GraphBindings[string]>) {
    const binding = bindings[slotId]
    if (binding) onBindingsChange({ ...bindings, [slotId]: { ...binding, ...patch } })
  }
  return <div className="wg-editor" onKeyDown={event => { if (event.key === 'Escape') { setPendingSource(null); setError('') } }}>
    <aside className="wg-library" aria-label="模块库"><div className="wg-panel-heading"><span>模块库</span><small>7 项能力</small></div><p className="wg-hint">点击添加，可重复使用。</p>
      <div className="wg-library-list">{GRAPH_NODE_KINDS.map(kind => <button type="button" key={kind} onClick={() => {
        const added = createNode(kind, graph)
        onChange({ ...graph, nodes: [...graph.nodes, added] }); setSelectedId(added.id); setError('')
      }} aria-label={`添加${GRAPH_CATALOG[kind].label}`}><span className={`wg-module-symbol kind-${kind}`} aria-hidden="true">{kind === 'tts' ? '♫' : kind === 'translate' ? '译' : kind === 'mix' ? '≋' : kind === 'export' ? '↗' : kind === 'align' ? '↔' : kind === 'asr' ? '文' : '∿'}</span><span>{GRAPH_CATALOG[kind].label}<small>{Object.values(GRAPH_CATALOG[kind].inputs).join(' + ')} → {Object.values(GRAPH_CATALOG[kind].outputs).join(', ')}</small></span><b aria-hidden="true">+</b></button>)}</div>
      <div className="wg-slot-tools"><strong>添加输入槽</strong>{(['audio', 'subtitle'] as const).map(type => <button type="button" key={type} onClick={() => {
        let index = 1
        while (graph.input_slots.some(slot => slot.id === `${type}_${index}`)) index++
        onChange({ ...graph, input_slots: [...graph.input_slots, { id: `${type}_${index}`, type, label: `${type === 'audio' ? '音频' : '字幕'}输入 ${index}` }] })
      }}>+ {type === 'audio' ? '音频槽' : '字幕槽'}</button>)}</div>
      <div className="wg-library-note"><strong>素材与模板分开</strong><p>模板记住输入槽、连线和参数。每次使用时，再指定当前素材。</p></div>
    </aside>
    <main className="wg-main"><div className="wg-canvas-toolbar"><div><strong>流程画布</strong><span>{graph.nodes.length} 节点 · {graph.edges.length} 连线</span></div><button type="button" onClick={() => setMoved({})}>整理布局</button></div>
      <div className="wg-connect-instruction" role="status">{pendingSource ? <><strong>已选：{sourceLabel(graph, pendingSource)}</strong><span>点击目标输入完成连线</span><button type="button" onClick={() => setPendingSource(null)}>取消</button></> : <><i className="wg-port-dot subtitle" /><span>选择输出端口，再选择输入端口；也可在右侧指定来源。</span></>}</div>
      {error && <div className="wg-connection-error" role="alert">{error}</div>}
      <div className="wg-canvas-scroll" role="region" aria-label="节点画布" tabIndex={0}>
        <div className="wg-canvas-stage" ref={stageRef} style={{ width: layout.width, height: Math.max(layout.height, ...Object.values(positions).map(point => point.y + 230)) }} onPointerMove={move} onPointerUp={() => { dragRef.current = null }} onPointerCancel={() => { dragRef.current = null }}>
          <svg className="wg-connections" width="100%" height="100%" aria-hidden="true"><defs><marker id="wg-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8z" fill="currentColor" /></marker></defs>{lines.map(line => <path key={line.id} className={`wg-line ${line.type}`} d={line.path} markerEnd="url(#wg-arrow)" />)}</svg>
          {graph.input_slots.map(slot => {
            const source: GraphEdge['source'] = { kind: 'slot', slot_id: slot.id }
            const point = positions[`slot:${slot.id}`]!
            const binding = bindings[slot.id]
            const material = materials.find(item => item.path === binding?.path)
            return <article className={`wg-slot ${binding ? '' : 'has-issue'}`} key={slot.id} style={{ left: point.x, top: point.y }}>
              <div className="wg-slot-label"><span>输入槽</span><b>{TYPE_NAMES[slot.type]}</b></div><h3>{slot.label}</h3>
              <label className="wg-field"><span className="wg-visually-hidden">{slot.label} 素材</span><select aria-label={`${slot.label} 素材`} value={binding?.path || ''} onChange={event => {
                const next = { ...bindings }; const selected = materials.find(item => item.path === event.target.value)
                if (selected) next[slot.id] = { path: selected.path, ...(selected.language ? { language: selected.language } : {}) }
                else delete next[slot.id]
                onBindingsChange(next)
              }}><option value="">选择本次素材</option>{binding && !materials.some(item => item.path === binding.path) && <option value={binding.path}>原素材不可用</option>}{materials.filter(item => item.type === slot.type).map(item => <option key={item.id} value={item.path}>{item.name}</option>)}</select></label>
              {slot.type === 'subtitle' && material && !material.language && <div className="wg-language-confirm"><select aria-label={`${slot.label} 确认语言`} value={binding?.language || ''} onChange={event => patchBinding(slot.id, { language: event.target.value as 'ja' | 'zh' | 'en', language_confirmed: false })}><option value="">确认字幕语言</option><option value="zh">中文</option><option value="ja">日语</option><option value="en">英语</option></select><label><input type="checkbox" checked={!!binding?.language_confirmed} disabled={!binding?.language} onChange={event => patchBinding(slot.id, { language_confirmed: event.target.checked })} />已核实语言</label></div>}
              <div className="wg-slot-meta">{material ? `${material.valid ? '素材已指定' : '素材无效'}${material.language ? ` · ${material.language}` : ' · 语言待确认'}` : '尚未指定素材'}{slot.language ? ` · 要求 ${slot.language}` : ''}</div>
              <button type="button" className={`wg-port output ${pendingSource && sourceKey(pendingSource) === sourceKey(source) ? 'armed' : ''}`} data-endpoint={`source:${sourceKey(source)}`} onClick={() => { setPendingSource(source); setError('') }} aria-label={`从输入槽 ${slot.id} 连线`}><span>{TYPE_NAMES[slot.type]}</span><i className={`wg-port-dot ${slot.type}`} /></button>
            </article>
          })}
          {graph.nodes.map(item => <div className="wg-node-position" key={item.id} style={{ left: positions[item.id]!.x, top: positions[item.id]!.y }}><WorkflowNode node={item} graph={graph} selected={item.id === selectedId} issues={issues.filter(issue => issue.nodeId === item.id).map(issue => issue.message)} pendingSource={pendingSource}
            onSelect={() => setSelectedId(item.id)} onSource={source => { setPendingSource(source); setError('') }} onTarget={target => { if (pendingSource) connect(target, pendingSource) }} onMoveStart={event => moveStart(item.id, event)} /></div>)}
        </div>
      </div>
      <div className="wg-deliveries"><strong>本次交付</strong>{graph.outputs.length ? graph.outputs.map(output => {
        const outputNode = graph.nodes.find(item => item.id === output.node_id)
        return <span key={`${output.node_id}:${output.port}`}>{output.label || `${outputNode ? GRAPH_CATALOG[outputNode.kind].label : '节点已移除'} · ${output.node_id}`}</span>
      }) : <span className="wg-warning">尚未选择产出</span>}</div>
      <details className="wg-problems" open={allIssues.length > 0}><summary>{allIssues.length ? `${allIssues.length} 项需要补充` : '结构与示例素材已连接'}<span>仅检查图与素材，不代表引擎已就绪</span></summary>{allIssues.map((issue, index) => <p key={index}>{issue}</p>)}</details>
    </main>
    <WorkflowInspector graph={graph} node={node} issues={issues.filter(issue => issue.nodeId === selectedId).map(issue => issue.message)} onNodeChange={updated => onChange(updateNode(graph, updated))} onConnect={connect} renderParameters={renderParameters} onRemove={id => { onChange(removeNode(graph, id)); setPendingSource(null) }} onOutput={(id, port, selected) => {
      const outputs = graph.outputs.filter(output => output.node_id !== id || output.port !== port)
      onChange({ ...graph, outputs: selected ? [...outputs, { node_id: id, port }] : outputs })
    }} />
  </div>
}
