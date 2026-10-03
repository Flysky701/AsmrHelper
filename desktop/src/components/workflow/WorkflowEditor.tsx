import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { GRAPH_CATALOG, GRAPH_NODE_KINDS, type GraphDefinition, type GraphNode, type GraphNodeKind, type GraphEdge, type GraphBindings } from '@/domain/workflowGraph'
import { WorkflowNode } from './WorkflowNode'
import { WorkflowInspector } from './WorkflowInspector'
import { bindingIssues, connectPort, removeNode, removeInputSlot, sourceKey, sourceLabel, TYPE_NAMES, updateNode, updateInputSlot, type WorkflowMaterial } from './graphEditorModel'
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
  /** Template editing defines slots; concrete material bindings belong to Workbench. */
  templateMode?: boolean
}
type Point = { x: number; y: number }
type Line = { id: string; path: string; type: string }

function autoPositions(graph: GraphDefinition, narrow: boolean, templateMode: boolean): { points: Record<string, Point>; width: number; height: number } {
  const rowHeight = templateMode ? 290 : 235
  if (narrow) return { points: Object.fromEntries([...graph.input_slots.map(slot => `slot:${slot.id}`), ...graph.nodes.map(node => node.id)].map((id, index) => [id, { x: 48, y: 30 + index * rowHeight }])), width: 302, height: Math.max(440, (graph.input_slots.length + graph.nodes.length) * rowHeight + 45) }
  const depth: Record<string, number> = Object.fromEntries(graph.nodes.map(node => [node.id, 1]))
  for (let pass = 0; pass < graph.nodes.length; pass++) {
    for (const edge of graph.edges) if (edge.source.kind === 'node') depth[edge.target.node_id] = Math.min(graph.nodes.length, Math.max(depth[edge.target.node_id] || 1, (depth[edge.source.node_id] || 1) + 1))
  }
  const layers: Record<number, string[]> = { 0: graph.input_slots.map(slot => `slot:${slot.id}`) }
  graph.nodes.forEach(node => { const layer = depth[node.id] || 1; (layers[layer] ||= []).push(node.id) })
  const maxCount = Math.max(2, ...Object.values(layers).map(items => items.length))
  const height = Math.max(520, maxCount * rowHeight + 45)
  const points: Record<string, Point> = {}
  for (const [layer, ids] of Object.entries(layers)) ids.forEach((id, index) => { points[id] = { x: 26 + Number(layer) * 262, y: 28 + index * rowHeight + (maxCount - ids.length) * 28 } })
  return { points, width: 26 + (Math.max(0, ...Object.values(depth)) + 1) * 262, height }
}

export default function WorkflowEditor({ graph, bindings, materials, issues, onChange, onBindingsChange, createNode, renderParameters, templateMode = false }: WorkflowEditorProps) {
  const [selectedId, setSelectedId] = useState(graph.nodes[0]?.id || '')
  const [pendingSource, setPendingSource] = useState<GraphEdge['source'] | null>(null)
  const [error, setError] = useState('')
  const [removal, setRemoval] = useState<{ kind: 'slot' | 'node'; id: string; graph: GraphDefinition } | null>(null)
  const [editorWidth, setEditorWidth] = useState(1000)
  const [narrow, setNarrow] = useState(false)
  const [compactPane, setCompactPane] = useState<'canvas' | 'inspector'>('canvas')
  const [moved, setMoved] = useState<Record<string, Point>>({})
  const [lines, setLines] = useState<Line[]>([])
  const [measuredExtent, setMeasuredExtent] = useState({ width: 0, height: 0 })
  const editorRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ id: string; x: number; y: number; origin: Point; scrollLeft: number; scrollTop: number } | null>(null)
  const revealRef = useRef<string | null>(null)
  const layout = autoPositions(graph, narrow, templateMode)
  // Deleted nodes cannot keep the stage expanded through an obsolete drag position.
  const positions = Object.fromEntries(Object.entries(layout.points).map(([id, point]) => [id, narrow ? point : moved[id] || point]))
  const extent = { width: Math.max(layout.width, measuredExtent.width, ...Object.values(positions).map(point => point.x + 242)),
    height: Math.max(layout.height, measuredExtent.height, ...Object.values(positions).map(point => point.y + 260)) }
  const node = graph.nodes.find(item => item.id === selectedId)
  const materialIssues = templateMode ? [] : bindingIssues(graph, bindings, materials)
  const allIssues = [...issues.map(issue => issue.message), ...materialIssues]
  useLayoutEffect(() => {
    const editor = editorRef.current, scroll = scrollRef.current
    if (!editor || !scroll) return
    const measure = () => {
      setEditorWidth(editor.clientWidth)
      // The available canvas width, rather than window width or device pixels,
      // determines whether the compact one-column arrangement is useful.
      if (scroll.clientWidth) setNarrow(scroll.clientWidth < 340)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(editor); observer.observe(scroll)
    return () => observer.disconnect()
  }, [])
  useEffect(() => { if (!graph.nodes.some(item => item.id === selectedId)) setSelectedId(graph.nodes[0]?.id || '') }, [graph.nodes, selectedId])
  useLayoutEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const measure = () => {
      const origin = stage.getBoundingClientRect()
      const cards = Array.from(stage.querySelectorAll<HTMLElement>('[data-canvas-id]'))
      const bounds = { width: Math.max(0, ...cards.map(card => card.offsetLeft + card.offsetWidth + 36)),
        height: Math.max(0, ...cards.map(card => card.offsetTop + card.offsetHeight + 36)) }
      setMeasuredExtent(current => current.width === bounds.width && current.height === bounds.height ? current : bounds)
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
    stage.querySelectorAll<HTMLElement>('[data-canvas-id]').forEach(card => observer.observe(card))
    return () => observer.disconnect()
  }, [graph, bindings, narrow, moved])
  function reveal(id: string) {
    const scroll = scrollRef.current, stage = stageRef.current
    const card = Array.from(stage?.querySelectorAll<HTMLElement>('[data-canvas-id]') || []).find(item => item.dataset.canvasId === id)
    if (!scroll || !card) return
    scroll.scrollTo({ left: Math.max(0, card.offsetLeft - 24), top: Math.max(0, card.offsetTop - 24), behavior: 'instant' })
  }
  useLayoutEffect(() => {
    if (!revealRef.current) return
    const id = revealRef.current
    revealRef.current = null
    reveal(id)
  }, [graph.nodes.length, graph.input_slots.length, narrow, compactPane])
  function connect(target: GraphEdge['target'], source: GraphEdge['source'] | null) {
    const result = connectPort(graph, target, source)
    setError(result.error)
    if (!result.error) { onChange(result.graph); setPendingSource(null) }
  }
  function moveStart(id: string, event: PointerEvent<HTMLElement>) {
    if (narrow || event.button !== 0) return
    dragRef.current = { id, x: event.clientX, y: event.clientY, origin: positions[id]!, scrollLeft: scrollRef.current?.scrollLeft || 0, scrollTop: scrollRef.current?.scrollTop || 0 }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (!drag || narrow) return
    const x = Math.max(10, drag.origin.x + event.clientX - drag.x + (scrollRef.current?.scrollLeft || 0) - drag.scrollLeft)
    const y = Math.max(12, drag.origin.y + event.clientY - drag.y + (scrollRef.current?.scrollTop || 0) - drag.scrollTop)
    setMoved(current => ({ ...current, [drag.id]: { x, y } }))
  }
  function confirmRemoval() {
    if (!removal) return
    if (removal.graph !== graph) { setRemoval(null); setError('流程已更改，请重新选择要删除的卡片。'); return }
    if (removal.kind === 'slot') {
      onChange(removeInputSlot(graph, removal.id))
      const next = { ...bindings }; delete next[removal.id]; onBindingsChange(next)
    } else onChange(removeNode(graph, removal.id))
    setRemoval(null); setPendingSource(null)
    setError('已删除卡片及关联连线与产出；下游需要重新指定来源。素材文件保持不变。')
  }
  function patchBinding(slotId: string, patch: Partial<GraphBindings[string]>) {
    const binding = bindings[slotId]
    if (binding) onBindingsChange({ ...bindings, [slotId]: { ...binding, ...patch } })
  }
  return <div ref={editorRef} className={`wg-editor${editorWidth < 960 ? ' is-condensed' : ''}${editorWidth < 720 ? ' is-compact' : ''}${editorWidth < 540 ? ' is-small' : ''} show-${compactPane}${narrow ? ' has-narrow-canvas' : ''}`} onKeyDown={event => { if (event.key === 'Escape') { setPendingSource(null); setRemoval(null); setError('') } }}>
    <aside className="wg-library" aria-label="模块库" tabIndex={0}><div className="wg-panel-heading"><span>模块库</span><small>{GRAPH_NODE_KINDS.length} 项能力</small></div><p className="wg-hint">点击添加，可重复使用。</p>
      <div className="wg-library-list">{GRAPH_NODE_KINDS.map(kind => <button type="button" key={kind} onClick={() => {
        const added = createNode(kind, graph)
        revealRef.current = added.id; setCompactPane('canvas')
        onChange({ ...graph, nodes: [...graph.nodes, added] }); setSelectedId(added.id); setError('')
      }} aria-label={`添加${GRAPH_CATALOG[kind].label}`}><span className={`wg-module-symbol kind-${kind}`} aria-hidden="true">{kind === 'tts' ? '♫' : kind === 'translate' ? '译' : kind === 'mix' ? '≋' : ['export', 'audio_export'].includes(kind) ? '↗' : kind === 'align' ? '↔' : kind === 'asr' ? '文' : '∿'}</span><span>{GRAPH_CATALOG[kind].label}<small>{Object.values(GRAPH_CATALOG[kind].inputs).join(' + ')} → {Object.values(GRAPH_CATALOG[kind].outputs).join(', ')}</small></span><b aria-hidden="true">+</b></button>)}</div>
      <div className="wg-slot-tools"><strong>添加输入槽</strong>{(['audio', 'subtitle'] as const).map(type => <button type="button" key={type} onClick={() => {
        let index = 1
        while (graph.input_slots.some(slot => slot.id.toLowerCase() === `${type}_${index}`)) index++
        revealRef.current = `slot:${type}_${index}`; setCompactPane('canvas')
        onChange({ ...graph, input_slots: [...graph.input_slots, { id: `${type}_${index}`, type, label: `${type === 'audio' ? '音频' : '字幕'}输入 ${index}` }] })
      }}>+ {type === 'audio' ? '音频槽' : '字幕槽'}</button>)}</div>
      <div className="wg-library-note"><strong>素材与模板分开</strong><p>模板记住输入槽、连线和参数。每次使用时，再指定当前素材。</p></div>
    </aside>
    <nav className="wg-pane-switch" aria-label="编辑区域"><button type="button" aria-pressed={compactPane === 'canvas'} onClick={() => setCompactPane('canvas')}>流程画布</button><button type="button" aria-pressed={compactPane === 'inspector'} onClick={() => setCompactPane('inspector')}>节点设置{node ? ` · ${node.id}` : ''}</button></nav>
    <main className="wg-main"><div className="wg-canvas-toolbar"><div><strong>流程画布</strong><span>{graph.nodes.length} 节点 · {graph.edges.length} 连线</span></div><div className="wg-canvas-actions"><select aria-label="定位画布节点" value="" onChange={event => { const id = event.target.value; if (!id) return; if (!id.startsWith('slot:')) setSelectedId(id); reveal(id) }}><option value="">定位节点…</option>{graph.input_slots.map(slot => <option key={`slot:${slot.id}`} value={`slot:${slot.id}`}>{slot.label} · {slot.id}</option>)}{graph.nodes.map(item => <option key={item.id} value={item.id}>{GRAPH_CATALOG[item.kind].label} · {item.id}</option>)}</select><button type="button" onClick={() => { setMoved({}); scrollRef.current?.scrollTo({ left: 0, top: 0 }) }}>整理布局</button></div></div>
      <div className="wg-connect-instruction" role="status">{pendingSource ? <><strong>已选：{sourceLabel(graph, pendingSource)}</strong><span>点击目标输入完成连线</span><button type="button" onClick={() => setPendingSource(null)}>取消</button></> : <><i className="wg-port-dot subtitle" /><span>选择输出端口，再选择输入端口；也可在右侧指定来源。</span></>}</div>
      {error && <div className="wg-connection-error" role="alert">{error}</div>}
      {removal && <section className="wg-delete-confirm" aria-label="确认删除卡片">
        <p>删除{removal.kind === 'slot' ? '输入槽' : '节点'}「{removal.id}」及其关联连线{removal.kind === 'node' ? '与产出' : ''}？下游会缺少来源；素材文件和历史任务保持不变。</p>
        <div><button type="button" autoFocus onClick={() => setRemoval(null)}>取消</button><button type="button" onClick={confirmRemoval}>确认删除</button></div>
      </section>}
      <div className="wg-canvas-scroll" ref={scrollRef} role="region" aria-label="节点画布" tabIndex={0}>
        <div className="wg-canvas-stage" ref={stageRef} style={{ width: extent.width, height: extent.height }} onPointerMove={move} onPointerUp={() => { dragRef.current = null }} onPointerCancel={() => { dragRef.current = null }}>
          <svg className="wg-connections" width="100%" height="100%" aria-hidden="true"><defs><marker id="wg-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8z" fill="currentColor" /></marker></defs>{lines.map(line => <path key={line.id} className={`wg-line ${line.type}`} d={line.path} markerEnd="url(#wg-arrow)" />)}</svg>
          {graph.input_slots.map(slot => {
            const source: GraphEdge['source'] = { kind: 'slot', slot_id: slot.id }
            const point = positions[`slot:${slot.id}`]!
            const binding = bindings[slot.id]
            const material = materials.find(item => item.path === binding?.path)
            return <article className={`wg-slot ${templateMode || binding ? '' : 'has-issue'}`} data-canvas-id={`slot:${slot.id}`} key={slot.id} style={{ left: point.x, top: point.y }}>
              <div className="wg-slot-label"><span>输入槽 · {TYPE_NAMES[slot.type]}</span>{templateMode && <button type="button" className="wg-card-remove" aria-label={`删除输入槽 ${slot.id}`} title="删除输入槽及关联连线；不会删除素材文件" onClick={() => setRemoval({ kind: 'slot', id: slot.id, graph })}><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 10v7M14 10v7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg></button>}</div><h3>{slot.label}</h3>
              {templateMode ? <>
                <label className="wg-field"><span>名称</span><input aria-label={`${slot.id} 输入槽名称`} maxLength={100} value={slot.label} onChange={event => onChange(updateInputSlot(graph, { ...slot, label: event.target.value }))} /></label>
                <label className="wg-field"><span>要求的语言</span><select aria-label={`${slot.id} 输入槽语言`} value={slot.language || ''} onChange={event => onChange(updateInputSlot(graph, { ...slot, language: (event.target.value || null) as typeof slot.language }))}><option value="">使用时确认</option><option value="zh">中文</option><option value="ja">日语</option><option value="en">英语</option></select></label>
              </> : <><label className="wg-field"><span className="wg-visually-hidden">{slot.label} 素材</span><select aria-label={`${slot.label} 素材`} value={binding?.path || ''} onChange={event => {
                const next = { ...bindings }; const selected = materials.find(item => item.path === event.target.value)
                if (selected) next[slot.id] = { path: selected.path, ...(selected.language ? { language: selected.language } : {}) }
                else delete next[slot.id]
                onBindingsChange(next)
              }}><option value="">选择本次素材</option>{binding && !materials.some(item => item.path === binding.path) && <option value={binding.path}>原素材不可用</option>}{materials.filter(item => item.type === slot.type).map(item => <option key={item.id} value={item.path}>{item.name}</option>)}</select></label>
              {slot.type === 'subtitle' && material && !material.language && <div className="wg-language-confirm"><select aria-label={`${slot.label} 确认语言`} value={binding?.language || ''} onChange={event => patchBinding(slot.id, { language: event.target.value as 'ja' | 'zh' | 'en', language_confirmed: false })}><option value="">确认字幕语言</option><option value="zh">中文</option><option value="ja">日语</option><option value="en">英语</option></select><label><input type="checkbox" checked={!!binding?.language_confirmed} disabled={!binding?.language} onChange={event => patchBinding(slot.id, { language_confirmed: event.target.checked })} />已核实语言</label></div>}
              <div className="wg-slot-meta">{material ? `${material.valid ? '素材已指定' : '素材无效'}${material.language ? ` · ${material.language}` : ' · 语言待确认'}` : '尚未指定素材'}{slot.language ? ` · 要求 ${slot.language}` : ''}</div></>}
              <button type="button" className={`wg-port output ${pendingSource && sourceKey(pendingSource) === sourceKey(source) ? 'armed' : ''}`} data-endpoint={`source:${sourceKey(source)}`} onClick={() => { setPendingSource(source); setError('') }} aria-label={`从输入槽 ${slot.id} 连线`}><span>{TYPE_NAMES[slot.type]}</span><i className={`wg-port-dot ${slot.type}`} /></button>
            </article>
          })}
          {graph.nodes.map(item => <div className="wg-node-position" data-canvas-id={item.id} key={item.id} style={{ left: positions[item.id]!.x, top: positions[item.id]!.y }}><WorkflowNode node={item} graph={graph} selected={item.id === selectedId} issues={issues.filter(issue => issue.nodeId === item.id).map(issue => issue.message)} pendingSource={pendingSource}
            onSelect={() => setSelectedId(item.id)} onRemove={() => setRemoval({ kind: 'node', id: item.id, graph })} onSource={source => { setPendingSource(source); setError('') }} onTarget={target => { if (pendingSource) connect(target, pendingSource) }} onMoveStart={event => moveStart(item.id, event)} /></div>)}
        </div>
      </div>
      <div className="wg-deliveries"><strong>{templateMode ? '流水线产出' : '本次交付'}</strong>{graph.outputs.length ? graph.outputs.map(output => {
        const outputNode = graph.nodes.find(item => item.id === output.node_id)
        return <span key={`${output.node_id}:${output.port}`}>{output.label || `${outputNode ? GRAPH_CATALOG[outputNode.kind].label : '节点已移除'} · ${output.node_id}`}</span>
      }) : <span className="wg-warning">尚未选择产出</span>}</div>
      <details className="wg-problems" open={allIssues.length > 0}><summary>{allIssues.length ? `${allIssues.length} 项需要补充` : templateMode ? '结构检查通过' : '结构与素材已连接'}<span>{templateMode ? '保存模板不运行任务；素材与环境在工作台检查' : '仅检查图与素材，不代表引擎已就绪'}</span></summary>{allIssues.map((issue, index) => <p key={index}>{issue}</p>)}</details>
    </main>
    <WorkflowInspector graph={graph} node={node} issues={issues.filter(issue => issue.nodeId === selectedId).map(issue => issue.message)} onNodeChange={updated => onChange(updateNode(graph, updated))} onConnect={connect} renderParameters={renderParameters} onOutput={(id, port, selected) => {
      const outputs = graph.outputs.filter(output => output.node_id !== id || output.port !== port)
      onChange({ ...graph, outputs: selected ? [...outputs, { node_id: id, port }] : outputs })
    }} />
  </div>
}
