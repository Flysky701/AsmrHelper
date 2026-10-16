import { t, format, useI18n } from '@/i18n'
import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { graphNodeInputs, GRAPH_CATALOG, GRAPH_ADDABLE_NODE_KINDS, type GraphDefinition, type GraphNode, type GraphNodeKind, type GraphEdge, type GraphBindings } from '@/domain/workflowGraph'
import { WorkflowNode } from './WorkflowNode'
import { WorkflowInspector } from './WorkflowInspector'
import { bindingIssues, connectPort, removeNode, removeInputSlot, sourceKey, TYPE_NAMES, updateNode, updateInputSlot, type WorkflowMaterial } from './graphEditorModel'
import { MIN_CANVAS_ZOOM, MAX_CANVAS_ZOOM, clampCanvasZoom, canvasPoint, zoomedScroll, draggedCanvasPoint, fitCanvasView, pannedCanvasScroll } from './canvasViewport'
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
  const cardHeight = (id: string) => {
    const node = graph.nodes.find(item => item.id === id)
    return node ? Math.max(rowHeight, 170 + Object.keys(graphNodeInputs(node)).length * 32) : rowHeight
  }
  if (narrow) {
    let y = 30
    const points = Object.fromEntries([...graph.input_slots.map(slot => `slot:${slot.id}`), ...graph.nodes.map(node => node.id)].map(id => {
      const point = { x: 48, y }; y += cardHeight(id); return [id, point]
    }))
    return { points, width: 302, height: Math.max(440, y + 45) }
  }
  const depth: Record<string, number> = Object.fromEntries(graph.nodes.map(node => [node.id, 1]))
  for (let pass = 0; pass < graph.nodes.length; pass++) {
    for (const edge of graph.edges) if (edge.source.kind === 'node') depth[edge.target.node_id] = Math.min(graph.nodes.length, Math.max(depth[edge.target.node_id] || 1, (depth[edge.source.node_id] || 1) + 1))
  }
  const layers: Record<number, string[]> = { 0: graph.input_slots.map(slot => `slot:${slot.id}`) }
  graph.nodes.forEach(node => { const layer = depth[node.id] || 1; (layers[layer] ||= []).push(node.id) })
  const maxCount = Math.max(2, ...Object.values(layers).map(items => items.length))
  const height = Math.max(520, ...Object.values(layers).map(ids => ids.reduce((total, id) => total + cardHeight(id), 0) + 45 + (maxCount - ids.length) * 28))
  const points: Record<string, Point> = {}
  for (const [layer, ids] of Object.entries(layers)) {
    let y = 28 + (maxCount - ids.length) * 28
    ids.forEach(id => { points[id] = { x: 26 + Number(layer) * 262, y }; y += cardHeight(id) })
  }
  return { points, width: 26 + (Math.max(0, ...Object.values(depth)) + 1) * 262, height }
}

export default function WorkflowEditor({ graph, bindings, materials, issues, onChange, onBindingsChange, createNode, renderParameters, templateMode = false }: WorkflowEditorProps) {
  useI18n()
  const [selectedId, setSelectedId] = useState(graph.nodes[0]?.id || '')
  const [pendingSource, setPendingSource] = useState<GraphEdge['source'] | null>(null)
  const [error, setError] = useState('')
  const [removal, setRemoval] = useState<{ kind: 'slot' | 'node'; id: string; graph: GraphDefinition } | null>(null)
  const [editorWidth, setEditorWidth] = useState(1000)
  const [narrow, setNarrow] = useState(false)
  const [compactPane, setCompactPane] = useState<'canvas' | 'inspector'>('canvas')
  const [moved, setMoved] = useState<Record<string, Point>>({})
  const [viewport, setViewport] = useState({ width: 0, height: 0 })
  const paddingRef = useRef<Point>({ x: 0, y: 0 })
  const panRef = useRef<{ pointerId: number; x: number; y: number; scroll: Point } | null>(null)
  const spaceRef = useRef(false)
  const [spaceHeld, setSpaceHeld] = useState(false)
  const [panning, setPanning] = useState(false)
  const [zoom, setZoom] = useState(1)
  const zoomRef = useRef(1)
  const pendingScrollRef = useRef<Point | null>(null)
  const [lines, setLines] = useState<Line[]>([])
  const [measuredExtent, setMeasuredExtent] = useState({ width: 0, height: 0 })
  const editorRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ id: string; x: number; y: number; origin: Point; zoom: number; scrollLeft: number; scrollTop: number } | null>(null)
  const revealRef = useRef<string | null>(null)
  const layout = autoPositions(graph, narrow, templateMode)
  // Deleted nodes cannot keep the stage expanded through an obsolete drag position.
  const positions = Object.fromEntries(Object.entries(layout.points).map(([id, point]) => [id, narrow ? point : moved[id] || point]))
  const extent = { width: Math.max(layout.width, measuredExtent.width, ...Object.values(positions).map(point => point.x + 242)),
    height: Math.max(layout.height, measuredExtent.height, ...Object.values(positions).map(point => point.y + 260)) }
  const node = graph.nodes.find(item => item.id === selectedId)
  const pendingNode = pendingSource?.kind === 'node' ? graph.nodes.find(item => item.id === pendingSource.node_id) : undefined
  const pendingLabel = pendingSource?.kind === 'slot' ? graph.input_slots.find(slot => slot.id === pendingSource.slot_id)?.label ?? t('已移除的输入槽') : pendingNode && pendingSource?.kind === 'node' ? `${t(GRAPH_CATALOG[pendingNode.kind].label)} · ${pendingNode.id} / ${pendingSource.port}` : t('已移除的节点')
  const materialIssues = templateMode ? [] : bindingIssues(graph, bindings, materials)
  const allIssues = [...issues.map(issue => issue.message), ...materialIssues]
  useLayoutEffect(() => {
    const editor = editorRef.current, scroll = scrollRef.current
    if (!editor || !scroll) return
    const measure = () => {
      setEditorWidth(editor.clientWidth)
      // The available canvas width, rather than window width or device pixels,
      // determines whether the compact one-column arrangement is useful.
      if (scroll.clientWidth) {
        setNarrow(scroll.clientWidth < 340)
        setViewport(current => current.width === scroll.clientWidth && current.height === scroll.clientHeight ? current
          : { width: scroll.clientWidth, height: scroll.clientHeight })
      }
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(editor); observer.observe(scroll)
    return () => observer.disconnect()
  }, [])
  useLayoutEffect(() => {
    const scroll = scrollRef.current, prior = paddingRef.current
    paddingRef.current = { x: viewport.width, y: viewport.height }
    if (scroll) scroll.scrollTo({ left: scroll.scrollLeft + viewport.width - prior.x,
      top: scroll.scrollTop + viewport.height - prior.y, behavior: 'instant' })
  }, [viewport.width, viewport.height])
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
        const { x: sx, y: sy } = canvasPoint({ x: start.left + start.width / 2, y: start.top + start.height / 2 }, { x: origin.left, y: origin.top }, zoom)
        const { x: tx, y: ty } = canvasPoint({ x: end.left + end.width / 2, y: end.top + end.height / 2 }, { x: origin.left, y: origin.top }, zoom)
        const curve = narrow ? `M${sx},${sy} C${sx + 38},${sy + 42} ${tx - 38},${ty - 42} ${tx},${ty}` : `M${sx},${sy} C${sx + 64},${sy} ${tx - 64},${ty} ${tx},${ty}`
        return [{ id: String(index), path: curve, type: graph.input_slots.find(slot => edge.source.kind === 'slot' && slot.id === edge.source.slot_id)?.type || (edge.source.kind === 'node' && edge.source.port === 'audio' ? 'audio' : 'subtitle') }]
      }))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(stage)
    stage.querySelectorAll<HTMLElement>('[data-canvas-id]').forEach(card => observer.observe(card))
    return () => observer.disconnect()
  }, [graph, bindings, narrow, moved, zoom])
  function reveal(id: string) {
    const scroll = scrollRef.current, stage = stageRef.current
    const card = Array.from(stage?.querySelectorAll<HTMLElement>('[data-canvas-id]') || []).find(item => item.dataset.canvasId === id)
    if (!scroll || !card) return
    scroll.scrollTo({ left: Math.max(0, viewport.width + card.offsetLeft * zoom - 24), top: Math.max(0, viewport.height + card.offsetTop * zoom - 24), behavior: 'instant' })
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
    if (narrow || event.button !== 0 || panRef.current) return
    dragRef.current = { id, x: event.clientX, y: event.clientY, origin: positions[id]!, zoom, scrollLeft: scrollRef.current?.scrollLeft || 0, scrollTop: scrollRef.current?.scrollTop || 0 }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (!drag || narrow) return
    const point = draggedCanvasPoint(drag.origin, {
      x: event.clientX - drag.x + (scrollRef.current?.scrollLeft || 0) - drag.scrollLeft,
      y: event.clientY - drag.y + (scrollRef.current?.scrollTop || 0) - drag.scrollTop,
    }, drag.zoom)
    setMoved(current => ({ ...current, [drag.id]: point }))
  }
  function applyView(next: number, scroll: Point) {
    zoomRef.current = next
    if (next === zoom) scrollRef.current?.scrollTo({ left: scroll.x, top: scroll.y, behavior: 'instant' })
    else { pendingScrollRef.current = scroll; setZoom(next) }
  }
  function changeZoom(value: number, anchor?: Point) {
    const scroll = scrollRef.current
    if (!scroll || dragRef.current || panRef.current) return
    const next = clampCanvasZoom(value)
    applyView(next, zoomedScroll({ x: scroll.scrollLeft, y: scroll.scrollTop },
      anchor ?? { x: scroll.clientWidth / 2, y: scroll.clientHeight / 2 }, zoomRef.current, next, { x: viewport.width, y: viewport.height }))
  }
  function fitNodes() {
    const scroll = scrollRef.current, stage = stageRef.current
    if (!scroll || !stage || dragRef.current || panRef.current) return
    const cards = Array.from(stage.querySelectorAll<HTMLElement>('[data-canvas-id]'))
    if (!cards.length) { applyView(1, { x: viewport.width, y: viewport.height }); return }
    const x = Math.min(...cards.map(card => card.offsetLeft)), y = Math.min(...cards.map(card => card.offsetTop))
    const view = fitCanvasView({ x, y, width: Math.max(...cards.map(card => card.offsetLeft + card.offsetWidth)) - x,
      height: Math.max(...cards.map(card => card.offsetTop + card.offsetHeight)) - y }, { width: scroll.clientWidth, height: scroll.clientHeight })
    applyView(view.zoom, { x: viewport.width + view.scroll.x, y: viewport.height + view.scroll.y })
  }
  useLayoutEffect(() => {
    const position = pendingScrollRef.current
    if (position) { scrollRef.current?.scrollTo({ left: position.x, top: position.y, behavior: 'instant' }); pendingScrollRef.current = null }
  }, [zoom])
  useEffect(() => {
    const scroll = scrollRef.current
    if (!scroll) return
    const wheel = (event: WheelEvent) => {
      // Plain wheel scrolls normally; Ctrl/Meta wheel remains the browser's gesture.
      if (!event.altKey || event.ctrlKey || event.metaKey || dragRef.current || panRef.current) return
      event.preventDefault()
      const rect = scroll.getBoundingClientRect()
      changeZoom(zoomRef.current * Math.exp(-Math.sign(event.deltaY) * 0.12),
        { x: event.clientX - rect.left - scroll.clientLeft, y: event.clientY - rect.top - scroll.clientTop })
    }
    scroll.addEventListener('wheel', wheel, { passive: false })
    return () => scroll.removeEventListener('wheel', wheel)
  }, [zoom, viewport.width, viewport.height])
  function editingTarget(target: EventTarget) {
    return target instanceof Element && Boolean(target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])'))
  }
  function stopPan() {
    const pan = panRef.current
    panRef.current = null; setPanning(false)
    if (pan && scrollRef.current?.hasPointerCapture(pan.pointerId)) scrollRef.current.releasePointerCapture(pan.pointerId)
  }
  function panStart(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || dragRef.current || editingTarget(event.target)) return
    const target = event.target as Element
    const rect = event.currentTarget.getBoundingClientRect()
    if (event.clientX >= rect.left + event.currentTarget.clientWidth || event.clientY >= rect.top + event.currentTarget.clientHeight) return
    if (!spaceRef.current && target.closest('[data-canvas-id]')) return
    event.preventDefault(); event.stopPropagation()
    const scroll = event.currentTarget
    panRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY,
      scroll: { x: scroll.scrollLeft, y: scroll.scrollTop } }
    scroll.setPointerCapture(event.pointerId)
    scroll.focus({ preventScroll: true }); setPanning(true)
  }
  function panMove(event: PointerEvent<HTMLDivElement>) {
    const pan = panRef.current
    if (!pan || pan.pointerId !== event.pointerId) return
    event.preventDefault()
    const point = pannedCanvasScroll(pan.scroll, { x: event.clientX - pan.x, y: event.clientY - pan.y })
    event.currentTarget.scrollTo({ left: point.x, top: point.y, behavior: 'instant' })
  }
  useEffect(() => {
    const releaseSpace = (event: KeyboardEvent) => { if (event.code === 'Space' || event.key === ' ') { spaceRef.current = false; setSpaceHeld(false) } }
    const cancel = () => { stopPan(); dragRef.current = null; spaceRef.current = false; setSpaceHeld(false) }
    const visibility = () => { if (document.hidden) cancel() }
    window.addEventListener('keyup', releaseSpace)
    window.addEventListener('blur', cancel)
    document.addEventListener('visibilitychange', visibility)
    return () => { window.removeEventListener('keyup', releaseSpace); window.removeEventListener('blur', cancel); document.removeEventListener('visibilitychange', visibility) }
  }, [])
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
    <aside className="wg-library" aria-label={t("模块库")} tabIndex={0}><div className="wg-panel-heading"><span>{t("模块库")}</span><small>{GRAPH_ADDABLE_NODE_KINDS.length} {t(" 项能力")}</small></div>
      <div className="wg-library-list">{GRAPH_ADDABLE_NODE_KINDS.map(kind => <button type="button" key={kind} onClick={() => {
        const added = createNode(kind, graph)
        revealRef.current = added.id; setCompactPane('canvas')
        onChange({ ...graph, nodes: [...graph.nodes, added] }); setSelectedId(added.id); setError('')
      }} aria-label={format("添加{0}", [t(GRAPH_CATALOG[kind].label)])}><span className={`wg-module-symbol kind-${kind}`} aria-hidden="true">{kind === 'tts' ? '♫' : kind === 'translate' ? t("译") : kind === 'mix' ? '≋' : ['export', 'audio_export'].includes(kind) ? '↗' : kind === 'align' ? '↔' : kind === 'asr' ? t("文") : '∿'}</span><span>{t(GRAPH_CATALOG[kind].label)}<small>{kind === 'mix' ? 'N × audio' : Object.values(GRAPH_CATALOG[kind].inputs).join(' + ')} → {Object.values(GRAPH_CATALOG[kind].outputs).join(', ')}</small></span><b aria-hidden="true">+</b></button>)}</div>
      <div className="wg-slot-tools"><strong>{t("添加输入槽")}</strong>{(['audio', 'subtitle'] as const).map(type => <button type="button" key={type} onClick={() => {
        let index = 1
        while (graph.input_slots.some(slot => slot.id.toLowerCase() === `${type}_${index}`)) index++
        revealRef.current = `slot:${type}_${index}`; setCompactPane('canvas')
        onChange({ ...graph, input_slots: [...graph.input_slots, { id: `${type}_${index}`, type, label: `${type === 'audio' ? '音频' : '字幕'}输入 ${index}` }] })
      }}>+ {type === 'audio' ? t("音频槽") : t("字幕槽")}</button>)}</div>
    </aside>
    <nav className="wg-pane-switch" aria-label={t("编辑区域")}><button type="button" aria-pressed={compactPane === 'canvas'} onClick={() => setCompactPane('canvas')}>{t("流程画布")}</button><button type="button" aria-pressed={compactPane === 'inspector'} onClick={() => setCompactPane('inspector')}>{t("节点设置")}{node ? ` · ${node.id}` : ''}</button></nav>
    <main className="wg-main"><div className="wg-canvas-toolbar"><div><strong>{t("流程画布")}</strong><span>{graph.nodes.length} {t(" 节点 · ")}{graph.edges.length} {t(" 连线")}</span></div><div className="wg-canvas-actions"><select aria-label={t("定位画布节点")} value="" onChange={event => { const id = event.target.value; if (!id) return; if (!id.startsWith('slot:')) setSelectedId(id); reveal(id) }}><option value="">{t("定位节点…")}</option>{graph.input_slots.map(slot => <option key={`slot:${slot.id}`} value={`slot:${slot.id}`}>{slot.label} · {slot.id}</option>)}{graph.nodes.map(item => <option key={item.id} value={item.id}>{t(GRAPH_CATALOG[item.kind].label)} · {item.id}</option>)}</select><button type="button" onClick={() => { setMoved({}); scrollRef.current?.scrollTo({ left: viewport.width, top: viewport.height }) }}>{t("整理布局")}</button></div></div>
      <div className="wg-zoom-toolbar" role="group" aria-label={t('画布缩放')}>
        <button type="button" aria-label={t('缩小画布')} disabled={zoom <= MIN_CANVAS_ZOOM} onClick={() => changeZoom(zoomRef.current / 1.2)}>−</button>
        <output aria-label={t('当前缩放')}>{Math.round(zoom * 100)}%</output>
        <button type="button" aria-label={t('放大画布')} disabled={zoom >= MAX_CANVAS_ZOOM} onClick={() => changeZoom(zoomRef.current * 1.2)}>+</button>
        <button type="button" onClick={fitNodes}>{t('适应全部节点')}</button>
        <button type="button" onClick={() => changeZoom(1)}>{t('恢复 100%')}</button>
        <span className="wg-zoom-help" title={t('画布聚焦时用 + / − 缩放，0 恢复，F 适应；Alt + 滚轮缩放；空白处或按住空格拖动平移。')}>{t('Alt + 滚轮缩放；空白处或空格拖动平移')}</span>
      </div>
      {pendingSource && <div className="wg-connect-instruction" role="status"><strong>{t("已选：")}{pendingLabel}</strong><span>{t("点击目标输入完成连线")}</span><button type="button" onClick={() => setPendingSource(null)}>{t("取消")}</button></div>}
      {error && <div className="wg-connection-error" role="alert">{t(error)}</div>}
      {removal && <section className="wg-delete-confirm" aria-label={t("确认删除卡片")}>
        <p>{format("删除{0}「{1}」及其关联连线{2}？下游会缺少来源；素材文件和历史任务保持不变。", [t(removal.kind === 'slot' ? '输入槽' : '节点'), removal.id, removal.kind === 'node' ? t('与产出') : ''])}</p>
        <div><button type="button" autoFocus onClick={() => setRemoval(null)}>{t("取消")}</button><button type="button" onClick={confirmRemoval}>{t("确认删除")}</button></div>
      </section>}
      <div className={`wg-canvas-scroll${panning ? ' is-panning' : ''}${spaceHeld ? ' is-space-panning' : ''}`} ref={scrollRef} role="region" aria-label={t("节点画布")} tabIndex={0}
        title={t('画布聚焦时用 + / − 缩放，0 恢复，F 适应；Alt + 滚轮缩放；空白处或按住空格拖动平移。')}
        onPointerDownCapture={panStart} onPointerMove={panMove} onPointerUp={stopPan} onPointerCancel={stopPan} onLostPointerCapture={stopPan}
        onKeyUp={event => { if ((event.code === 'Space' || event.key === ' ') && spaceRef.current) { event.preventDefault(); spaceRef.current = false; setSpaceHeld(false) } }}
        onKeyDown={event => {
          if (event.key === 'Escape') { stopPan(); spaceRef.current = false; setSpaceHeld(false) }
          if ((event.code === 'Space' || event.key === ' ') && !event.ctrlKey && !event.metaKey && !event.altKey && !editingTarget(event.target)) {
            event.preventDefault(); spaceRef.current = true; setSpaceHeld(true); return
          }
          if (event.target !== event.currentTarget || event.ctrlKey || event.metaKey || event.altKey) return
          if (['+', '=', '-', '0', 'f', 'F'].includes(event.key)) {
            event.preventDefault()
            if (event.key === '0') changeZoom(1)
            else if (event.key.toLowerCase() === 'f') fitNodes()
            else changeZoom(zoomRef.current * (event.key === '-' ? 1 / 1.2 : 1.2))
          }
        }}>
        <div className="wg-canvas-size" style={{ width: extent.width * zoom + viewport.width * 2, height: extent.height * zoom + viewport.height * 2 }}>
        <div className="wg-canvas-stage" ref={stageRef} style={{ left: viewport.width, top: viewport.height, width: extent.width, height: extent.height, transform: `scale(${zoom})` }} onPointerMove={move} onPointerUp={() => { dragRef.current = null }} onPointerCancel={() => { dragRef.current = null }}>
          <svg className="wg-connections" width="100%" height="100%" aria-hidden="true"><defs><marker id="wg-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8z" fill="currentColor" /></marker></defs>{lines.map(line => <path key={line.id} className={`wg-line ${line.type}`} d={line.path} markerEnd="url(#wg-arrow)" />)}</svg>
          {graph.input_slots.map(slot => {
            const source: GraphEdge['source'] = { kind: 'slot', slot_id: slot.id }
            const point = positions[`slot:${slot.id}`]!
            const binding = bindings[slot.id]
            const material = materials.find(item => item.path === binding?.path)
            return <article className={`wg-slot ${templateMode || binding ? '' : 'has-issue'}`} data-canvas-id={`slot:${slot.id}`} key={slot.id} style={{ left: point.x, top: point.y }}>
              <div className="wg-slot-label"><span>{t("输入槽 · ")}{t(TYPE_NAMES[slot.type] || slot.type)}</span>{templateMode && <button type="button" className="wg-card-remove" aria-label={format("删除输入槽 {0}", [slot.id])} title={t("删除输入槽及关联连线；不会删除素材文件")} onClick={() => setRemoval({ kind: 'slot', id: slot.id, graph })}><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 10v7M14 10v7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg></button>}</div><h3>{slot.label}</h3>
              {templateMode ? <>
                <label className="wg-field"><span>{t("名称")}</span><input aria-label={format("{0} 输入槽名称", [slot.id])} maxLength={100} value={slot.label} onChange={event => onChange(updateInputSlot(graph, { ...slot, label: event.target.value }))} /></label>
                <label className="wg-field"><span>{t("要求的语言")}</span><select aria-label={format("{0} 输入槽语言", [slot.id])} value={slot.language || ''} onChange={event => onChange(updateInputSlot(graph, { ...slot, language: (event.target.value || null) as typeof slot.language }))}><option value="">{t("使用时确认")}</option><option value="zh">{t("中文")}</option><option value="ja">{t("日语")}</option><option value="en">{t("英语")}</option></select></label>
              </> : <><label className="wg-field"><span className="wg-visually-hidden">{slot.label} {t(" 素材")}</span><select aria-label={format("{0} 素材", [slot.label])} value={binding?.path || ''} onChange={event => {
                const next = { ...bindings }; const selected = materials.find(item => item.path === event.target.value)
                if (selected) next[slot.id] = { path: selected.path, ...(selected.language ? { language: selected.language } : {}) }
                else delete next[slot.id]
                onBindingsChange(next)
              }}><option value="">{t("选择本次素材")}</option>{binding && !materials.some(item => item.path === binding.path) && <option value={binding.path}>{t("原素材不可用")}</option>}{materials.filter(item => item.type === slot.type).map(item => <option key={item.id} value={item.path}>{item.name}</option>)}</select></label>
              {slot.type === 'subtitle' && material && !material.language && <div className="wg-language-confirm"><select aria-label={format("{0} 确认语言", [slot.label])} value={binding?.language || ''} onChange={event => patchBinding(slot.id, { language: event.target.value as 'ja' | 'zh' | 'en', language_confirmed: false })}><option value="">{t("确认字幕语言")}</option><option value="zh">{t("中文")}</option><option value="ja">{t("日语")}</option><option value="en">{t("英语")}</option></select><label><input type="checkbox" checked={!!binding?.language_confirmed} disabled={!binding?.language} onChange={event => patchBinding(slot.id, { language_confirmed: event.target.checked })} />{t("已核实语言")}</label></div>}
              <div className="wg-slot-meta">{material ? `${material.valid ? t("素材已指定") : t("素材无效")}${material.language ? ` · ${material.language}` : t(" · 语言待确认")}` : t("尚未指定素材")}{slot.language ? format(" · 要求 {0}", [slot.language]) : ''}</div></>}
              <button type="button" className={`wg-port output ${pendingSource && sourceKey(pendingSource) === sourceKey(source) ? 'armed' : ''}`} data-endpoint={`source:${sourceKey(source)}`} onClick={() => { setPendingSource(source); setError('') }} aria-label={format("从输入槽 {0} 连线", [slot.id])}><span>{t(TYPE_NAMES[slot.type] || slot.type)}</span><i className={`wg-port-dot ${slot.type}`} /></button>
            </article>
          })}
          {graph.nodes.map(item => <div className="wg-node-position" data-canvas-id={item.id} key={item.id} style={{ left: positions[item.id]!.x, top: positions[item.id]!.y }}><WorkflowNode node={item} graph={graph} selected={item.id === selectedId} issues={issues.filter(issue => issue.nodeId === item.id).map(issue => issue.message)} pendingSource={pendingSource}
            onSelect={() => setSelectedId(item.id)} onRemove={() => setRemoval({ kind: 'node', id: item.id, graph })} onSource={source => { setPendingSource(source); setError('') }} onTarget={target => { if (pendingSource) connect(target, pendingSource) }} onMoveStart={event => moveStart(item.id, event)} /></div>)}
        </div>
      </div>
      </div>
      <div className="wg-deliveries"><strong>{templateMode ? t("流水线产出") : t("本次交付")}</strong>{graph.outputs.length ? graph.outputs.map(output => {
        const outputNode = graph.nodes.find(item => item.id === output.node_id)
        return <span key={`${output.node_id}:${output.port}`}>{output.label || `${outputNode ? t(GRAPH_CATALOG[outputNode.kind].label) : t("节点已移除")} · ${output.node_id}`}</span>
      }) : <span className="wg-warning">{t("尚未选择产出")}</span>}</div>
      <details className="wg-problems" open={allIssues.length > 0}><summary>{allIssues.length ? format("{0} 项需要补充", [allIssues.length]) : templateMode ? t("结构检查通过") : t("结构与素材已连接")}</summary>{allIssues.map((issue, index) => <p key={index}>{t(issue)}</p>)}</details>
    </main>
    <WorkflowInspector graph={graph} node={node} issues={issues.filter(issue => issue.nodeId === selectedId).map(issue => issue.message)} onNodeChange={updated => onChange(updateNode(graph, updated))} onConnect={connect} renderParameters={renderParameters} onOutput={(id, port, selected) => {
      const outputs = graph.outputs.filter(output => output.node_id !== id || output.port !== port)
      onChange({ ...graph, outputs: selected ? [...outputs, { node_id: id, port }] : outputs })
    }} />
  </div>
}
