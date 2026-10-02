import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { ApiError } from '@/api/client'
import { batchesApi } from '@/api/batches'
import { inputsApi } from '@/api/inputs'
import type { BatchRunResponse, GraphPresetItem, PresetItem } from '@/api/types'
import { usedGraphSlots } from '@/components/GraphRunBindings'
import QueueGroupRow, { queueOutputLabel } from '@/components/tasks/QueueGroupRow'
import GraphNodeParameters from '@/components/workflow/GraphNodeParameters'
import { graphNodeHasAdvancedParameters } from '@/domain/graphNodeParameters'
import { groupEditable, groupIssues, type QueueSubmission } from '@/domain/queueGroups'
import { GRAPH_CATALOG } from '@/domain/workflowGraph'
import { cloneDraft, draftFingerprint, editorDirty, runtimeDirty } from '@/domain/workflowDraft'
import { MAX_WORKBENCH_INPUTS, discoveredFileToInput, expandInputMaterials, inputPathKey, pathToInput, type WorkbenchInputItem } from '@/domain/workbenchInput'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { useNavStore } from '@/stores/navStore'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import { useWorkflowStore } from '@/stores/workflowStore'
import './Workbench.css'

const isGraphPreset = (preset: PresetItem | GraphPresetItem): preset is GraphPresetItem => 'version' in preset && preset.version === 2
const messageOf = (error: unknown) => error instanceof Error ? error.message : String(error)
const uncertainError = (error: unknown) => !(error instanceof ApiError) || error.status === 0 || error.status >= 500
type Filter = 'all' | 'draft' | 'running' | 'completed' | 'failed'

export default function Workbench() {
  const materials = useWorkbenchStore(), workflow = useWorkflowStore()
  const { selectFiles, selectFolder } = useFileSelector()
  const { selectedPreset, runtimeGraph: graph } = workflow
  const presets = workflow.catalog.filter(isGraphPreset)
  const [panelOpen, setPanelOpen] = useState(false)
  const [parameterSection, setParameterSection] = useState<'common' | 'advanced'>('common')
  const [filter, setFilter] = useState<Filter>('all'), [search, setSearch] = useState('')
  const [discovering, setDiscovering] = useState(false), [submitting, setSubmitting] = useState(false)
  const [batchAction, setBatchAction] = useState<string | null>(null), [dragOver, setDragOver] = useState(false)
  const [materialError, setMaterialError] = useState(''), [requestError, setRequestError] = useState(''), [historyError, setHistoryError] = useState('')
  const [copyName, setCopyName] = useState(''), [saveOpen, setSaveOpen] = useState(false), [savedNotice, setSavedNotice] = useState('')
  const active = useRef(true), importLock = useRef(false), submitLock = useRef(false), batchLock = useRef(false), historySequence = useRef(0)
  const busy = submitting || workflow.saving
  const dirty = runtimeDirty(selectedPreset, graph)
  const overrideCount = graph?.nodes.filter(node => draftFingerprint(node) !== draftFingerprint(selectedPreset?.graph.nodes.find(saved => saved.id === node.id))).length ?? 0
  useEffect(() => {
    const guard = () => !submitLock.current && !useWorkflowStore.getState().saving
    const beforeUnload = (event: BeforeUnloadEvent) => { if (!guard()) { event.preventDefault(); event.returnValue = '' } }
    useNavStore.getState().setNavigationGuard(guard)
    window.addEventListener('beforeunload', beforeUnload)
    return () => {
      if (useNavStore.getState().navigationGuard === guard) useNavStore.getState().setNavigationGuard(null)
      window.removeEventListener('beforeunload', beforeUnload)
    }
  }, [])
  useEffect(() => {
    active.current = true
    void useWorkflowStore.getState().loadCatalog()
    const current = useWorkflowStore.getState()
    useWorkbenchStore.getState().initializeQueue(current.runtimeGraph, current.bindings)
    return () => { active.current = false; historySequence.current++ }
  }, [])
  const loadBatches = useCallback(async () => {
    const sequence = ++historySequence.current
    try {
      const result = await batchesApi.list()
      if (!active.current || sequence !== historySequence.current) return
      for (const batch of result.batches) useWorkbenchStore.getState().receiveQueueBatch(batch)
      setHistoryError('')
    } catch (error) { if (active.current && sequence === historySequence.current) setHistoryError(`状态刷新失败：${messageOf(error)}。当前显示为上次已知状态。`) }
  }, [])
  useEffect(() => {
    let disposed = false, timer: number | undefined
    const poll = async () => { await loadBatches(); if (!disposed) timer = window.setTimeout(() => void poll(), 3000) }
    void poll()
    return () => { disposed = true; if (timer) window.clearTimeout(timer) }
  }, [loadBatches])

  const appendItems = (items: WorkbenchInputItem[]) => {
    const state = useWorkbenchStore.getState(), expanded = expandInputMaterials(items)
    const existing = new Set(state.inputItems.map(item => inputPathKey(item.path)))
    let room = Math.max(0, MAX_WORKBENCH_INPUTS - state.inputItems.length)
    const accepted = expanded.filter(item => existing.has(inputPathKey(item.path)) || room-- > 0)
    state.importQueueItems(accepted, useWorkflowStore.getState().runtimeGraph)
    if (accepted.length < expanded.length) setMaterialError(error => `${error} 素材库最多 ${MAX_WORKBENCH_INPUTS} 项，其余未导入。`.trim())
  }
  const resolvePaths = async (paths: string[]) => {
    if (!paths.length || importLock.current || submitLock.current) return
    const accepted = [...new Map(paths.filter(path => /\.(mp3|wav|flac|ogg|m4a|aac|wma|srt|vtt|lrc)$/i.test(path)).map(path => [inputPathKey(path), path])).values()].slice(0, MAX_WORKBENCH_INPUTS)
    if (!accepted.length) { setMaterialError('请选择音频或 SRT / VTT / LRC 字幕。'); return }
    importLock.current = true; setDiscovering(true); setMaterialError('')
    try {
      const result = await inputsApi.resolveItems(accepted)
      if (!active.current) return
      const returned = new Set(result.items.map(item => inputPathKey(item.path)))
      appendItems([...result.items, ...accepted.filter(path => !returned.has(inputPathKey(path))).map(pathToInput)])
      if (result.warnings.length) setMaterialError(error => [error, ...result.warnings].filter(Boolean).join(' '))
    } catch (error) { if (active.current) { appendItems(accepted.map(pathToInput)); setMaterialError(`已保留所选路径，文件检查失败：${messageOf(error)}。请检查与配对后再运行。`) } }
    finally { importLock.current = false; if (active.current) setDiscovering(false) }
  }
  const chooseFiles = async () => {
    if (busy || discovering) return
    const paths = await selectFiles({ filters: [FILE_FILTERS.audio, FILE_FILTERS.subtitle] })
    if (active.current) await resolvePaths(paths)
  }
  const scanFolder = async (directory: string) => {
    if (importLock.current || submitLock.current) return
    importLock.current = true; setDiscovering(true); setMaterialError('')
    try {
      const result = await batchesApi.discover(directory, useWorkbenchStore.getState().scanRecursive, MAX_WORKBENCH_INPUTS + 1, 'all')
      if (!active.current) return
      const discovered = result.files.slice(0, MAX_WORKBENCH_INPUTS)
      let items = discovered.map(discoveredFileToInput), warnings: string[] = []
      try {
        const inspected = await inputsApi.resolveItems(discovered.map(item => item.path))
        const byPath = new Map(inspected.items.map(item => [inputPathKey(item.path), item]))
        items = items.map(item => byPath.get(inputPathKey(item.path)) ?? item); warnings = inspected.warnings
      } catch (error) { warnings = [`文件检查失败：${messageOf(error)}；已保留扫描路径，请检查与配对。`] }
      if (!active.current) return
      appendItems(items)
      setMaterialError(error => [error, ...warnings, ...(result.files.length > MAX_WORKBENCH_INPUTS ? [`仅导入前 ${MAX_WORKBENCH_INPUTS} 项。`] : [])].filter(Boolean).join(' '))
    } catch (error) { if (active.current) setMaterialError(`扫描失败：${messageOf(error)}`) }
    finally { importLock.current = false; if (active.current) setDiscovering(false) }
  }
  const chooseFolder = async () => {
    const directory = await selectFolder()
    if (directory && active.current) { materials.setInputFolder(directory); await scanFolder(directory) }
  }
  const drop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault(); setDragOver(false)
    if (busy || discovering) return
    let paths = Array.from(event.dataTransfer.files).map(file => (file as File & { path?: string }).path || file.name)
    if (paths.some(path => !/[\\/]/.test(path))) {
      const directory = window.prompt('浏览器模式无法读取完整路径，请输入这些文件所在目录：')
      if (!directory) return
      paths = paths.map(path => /[\\/]/.test(path) ? path : `${directory}${directory.includes('/') ? '/' : '\\'}${path}`)
    }
    await resolvePaths(paths)
  }

  const rows = useMemo(() => materials.queueGroups.map(group => {
    const batch = group.run ? materials.queueBatches.find(batch => batch.batch_id === group.run!.batchId) : undefined
    const remote = batch?.items.find(item => item.item_id === group.run!.itemId)
    const issues = groupEditable(group) ? groupIssues(group, graph, materials.inputItems) : []
    const state = group.pendingRequestId ? 'unknown' : group.run ? remote?.state ?? 'unknown' : group.excluded ? 'excluded' : issues.length ? 'missing' : 'draft'
    return { group, batch, remote, issues, state }
  }), [materials.queueGroups, materials.queueBatches, graph, materials.inputItems])
  const selected = rows.filter(row => row.group.selected && !row.group.excluded && groupEditable(row.group))
  const invalidSelected = selected.filter(row => row.issues.length > 0)
  const draftRows = rows.filter(row => groupEditable(row.group) && !row.group.excluded)
  const counts = { all: rows.length, draft: draftRows.length, running: rows.filter(row => ['running', 'pending'].includes(row.state)).length,
    completed: rows.filter(row => row.state === 'completed').length, failed: rows.filter(row => ['failed', 'cancelled'].includes(row.state)).length }
  const visible = rows.filter(row => (filter === 'all' || filter === 'draft' && groupEditable(row.group) && !row.group.excluded
    || filter === 'running' && ['running', 'pending'].includes(row.state) || filter === 'completed' && row.state === 'completed'
    || filter === 'failed' && ['failed', 'cancelled'].includes(row.state))
    && (!search.trim() || `${row.group.label} ${row.group.materialPaths.join(' ')}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())))
  const selectable = visible.filter(row => groupEditable(row.group) && !row.group.excluded)

  const submitFrozen = async (submission: QueueSubmission) => {
    historySequence.current++
    try {
      const response = await batchesApi.create(submission.request)
      const expected = new Set(submission.request.groups.map(group => group.group_id))
      if (!response?.batch_id || response.client_request_id !== submission.request.client_request_id
        || response.items.length !== expected.size || response.items.some(item => !item.group_id || !expected.delete(item.group_id)) || expected.size) throw new Error('后端返回的组标识不完整，提交结果尚未确认')
      useWorkbenchStore.getState().receiveQueueBatch(response)
      if (active.current) { setRequestError(''); setFilter('all') }
    } catch (error) {
      const uncertain = uncertainError(error)
      useWorkbenchStore.getState().failQueueSubmission(messageOf(error), uncertain)
      if (active.current) setRequestError(uncertain ? `提交结果未知：${messageOf(error)}。请核实原请求，避免重复创建。` : messageOf(error))
    } finally { submitLock.current = false; if (active.current) setSubmitting(false) }
  }
  const run = async () => {
    if (submitLock.current || importLock.current || busy || useWorkbenchStore.getState().queueSubmission) return
    const state = useWorkbenchStore.getState(), current = useWorkflowStore.getState()
    const groups = state.queueGroups.filter(group => group.selected && !group.excluded && groupEditable(group)), currentGraph = current.runtimeGraph
    if (!currentGraph || !groups.length) { setRequestError('请选择流水线，并勾选要处理的素材组。'); return }
    const issues = groups.flatMap(group => groupIssues(group, currentGraph, state.inputItems).map(issue => `${group.label}：${issue}`))
    if (issues.length) { setRequestError(`已选组尚未全部就绪：${issues.join('；')}`); return }
    submitLock.current = true; setSubmitting(true); setRequestError('')
    const submission: QueueSubmission = { state: 'sending', createdAt: new Date().toISOString(), presetLabel: current.selectedPreset?.label ?? '流水线',
      request: { name: state.batchName.trim() || current.selectedPreset?.label || '工作台队列', client_request_id: crypto.randomUUID(),
        output: state.outputDirectory.trim() ? { directory: state.outputDirectory.trim() } : {}, max_parallel: 1,
        execution_profile: { version: 2, graph: cloneDraft(currentGraph) },
        groups: groups.map(group => ({ group_id: group.id, label: group.label,
          bindings: Object.fromEntries(usedGraphSlots(currentGraph).map(slot => [slot.id, cloneDraft(group.bindings[slot.id]!)])) })) } }
    state.beginQueueSubmission(submission)
    await submitFrozen(submission)
  }
  const recoverSubmission = async () => {
    const pending = useWorkbenchStore.getState().queueSubmission
    if (!pending || submitLock.current) return
    submitLock.current = true; setSubmitting(true)
    await submitFrozen(pending)
  }
  const actOnBatch = async (batch: BatchRunResponse, action: 'retry' | 'cancel') => {
    if (batchLock.current || useWorkbenchStore.getState().queueBatchActions[batch.batch_id]) return
    if (action === 'retry' && !batch.retry_available) { setRequestError(batch.retry_blocked_reason || '缺少可用的执行快照，不能按原参数重试。'); return }
    batchLock.current = true; setBatchAction(batch.batch_id); setRequestError(''); historySequence.current++
    useWorkbenchStore.getState().beginQueueBatchAction(batch, action)
    try {
      const response = action === 'retry' ? await batchesApi.retryFailed(batch.batch_id) : await batchesApi.cancel(batch.batch_id)
      useWorkbenchStore.getState().receiveQueueBatch(response)
      useWorkbenchStore.getState().clearQueueBatchAction(batch.batch_id)
    } catch (error) {
      if (!uncertainError(error)) useWorkbenchStore.getState().clearQueueBatchAction(batch.batch_id)
      if (active.current) setRequestError(`${action === 'retry' ? '按原参数重试' : '取消批次'}${uncertainError(error) ? '结果尚未确认，请刷新状态后核实' : '失败'}：${messageOf(error)}`)
    }
    finally { batchLock.current = false; if (active.current) setBatchAction(null) }
  }
  const openEditor = (preset: GraphPresetItem | null, useRuntime = false) => {
    if (busy) return
    if (editorDirty(workflow.editor) && !window.confirm('存在未保存的流水线编辑草稿。打开此结构将替换该编辑草稿；工作台素材和本次参数会保留。继续？')) return
    workflow.openEditor(preset, 'workbench', useRuntime); useNavStore.getState().setPage('workflow-presets')
  }
  const changePreset = (id: string) => {
    const preset = presets.find(item => item.id === id)
    if (!preset || preset.id === selectedPreset?.id || busy) return
    if (dirty && !window.confirm('切换流水线会清除未保存的本次参数；素材组和已提交结果会保留。继续？')) return
    workflow.selectPreset(preset); setSavedNotice('')
  }
  const saveParameters = async (mode: 'update' | 'copy') => {
    if (busy || !graph) return
    if (mode === 'update' && (!selectedPreset || !window.confirm(`将本次节点参数保存到“${selectedPreset.label}”？`))) return
    const saved = await workflow.saveRuntime(mode, mode === 'copy' ? copyName.trim() : undefined)
    if (saved && active.current) { setSavedNotice(`已保存“${saved.label}”`); setSaveOpen(false) }
  }

  return <div className={`queue-workbench${panelOpen ? ' panel-open' : ''}${dragOver ? ' is-dragging' : ''}`} onDragOver={event => { event.preventDefault(); if (!busy && !discovering) setDragOver(true) }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragOver(false) }} onDrop={event => void drop(event)}>
    <header className="queue-page-heading"><h1>工作台</h1><button type="button" onClick={() => useNavStore.getState().openTaskCenter('batches')}>批次历史 ↗</button></header>
    <div className="queue-body"><div className="queue-pane">
      <div className="queue-preset-toolbar"><label>流水线预设<select aria-label="已保存的流水线" value={selectedPreset?.id ?? ''} disabled={busy || workflow.catalogLoading} onChange={event => changePreset(event.target.value)}>
        <option value="">{workflow.catalogLoading ? '正在加载流水线…' : presets.length ? '请选择流水线' : '暂无已保存流水线'}</option>{selectedPreset && !presets.some(preset => preset.id === selectedPreset.id) ? <option value={selectedPreset.id}>{selectedPreset.label}（等待目录核对）</option> : null}{presets.map(preset => <option key={preset.id} value={preset.id}>{preset.label}{preset.builtin ? ' · 内置' : ''}</option>)}</select></label>
        <button type="button" className="queue-adjust" disabled={!graph} aria-expanded={panelOpen} onClick={() => setPanelOpen(value => !value)}>☷ 调整参数{dirty ? <span className="queue-count" aria-label={`${overrideCount} 个节点有临时覆盖`}>{overrideCount}</span> : null}</button>
        <button type="button" className="queue-link" disabled={busy} onClick={() => openEditor(selectedPreset, true)}>{selectedPreset ? '编辑流程 ↗' : graph ? '编辑保留草稿 ↗' : '新建流程 ↗'}</button><span className={`queue-parameter-summary${dirty ? ' changed' : ''}`}>{!selectedPreset && graph ? '● 保留的未保存流程草稿' : dirty ? `● ${overrideCount} 个节点有本次覆盖` : selectedPreset ? '● 使用预设参数' : '请选择或新建流水线'}</span>
      </div>
      <div className="queue-flow-summary">{graph ? <><span>输入：{usedGraphSlots(graph).map(slot => slot.label).join(' + ')}</span><span>· 包含</span>{graph.nodes.map(node => <Fragment key={node.id}><span title={`${node.id} · ${node.provider}`}>{GRAPH_CATALOG[node.kind].label}</span><span>·</span></Fragment>)}<strong>输出：{queueOutputLabel(graph)}</strong></> : <span>选择已保存的流水线，导入音频或字幕组成待处理队列。</span>}</div>
      {workflow.catalogError ? <div className="queue-notice" role="alert">{workflow.catalogError}<button type="button" onClick={() => void workflow.loadCatalog()}>重试加载</button></div> : null}
      {workflow.catalogNotice ? <div className="queue-draft-notice" role="status">{workflow.catalogNotice}</div> : null}
      {!workflow.catalogLoading && !workflow.catalogError && !presets.length ? <div className="queue-draft-notice">活动目录暂无节点流水线。可以新建，或在流水线编辑页恢复已移除的预设。<button type="button" disabled={busy} onClick={() => useNavStore.getState().setPage('workflow-presets')}>新建或恢复流水线</button></div> : null}
      {workflow.editor ? <div className="queue-draft-notice">保留{editorDirty(workflow.editor) ? '未保存的' : '上次的'}编辑草稿：{workflow.editor.label || '未命名流水线'}<button type="button" disabled={busy} onClick={() => useNavStore.getState().setPage('workflow-presets')}>继续编辑</button></div> : null}
      {materials.queueMigrationNotice ? <div className="queue-draft-notice">原素材与路径草稿已保留，请检查各组绑定后勾选运行。<button type="button" onClick={() => useWorkbenchStore.setState({ queueMigrationNotice: false })}>知道了</button></div> : null}
      {workflow.catalog.some(preset => !isGraphPreset(preset)) ? <details className="queue-legacy"><summary>旧版预设 · 转换查看</summary>{workflow.catalog.filter(preset => !isGraphPreset(preset)).map(preset => <button key={preset.id} type="button" disabled={busy} onClick={() => {
        if (editorDirty(workflow.editor) && !window.confirm('转换将替换未保存的编辑草稿；原预设与队列保留。继续？')) return
        void workflow.openLegacyEditor(preset as PresetItem, 'workbench').then(() => { if (active.current && !useWorkflowStore.getState().error) useNavStore.getState().setPage('workflow-presets') })
      }}>{preset.label} → 转换</button>)}</details> : null}
      <section className="queue-section" aria-label="处理队列">
        <div className="queue-tools"><div className="queue-heading"><h2>处理队列</h2><span className="queue-count">{rows.length}</span></div><nav className="queue-tabs" aria-label="队列筛选">{([['all', '全部'], ['draft', '待处理'], ['running', '处理中'], ['completed', '已完成'], ...(counts.failed ? [['failed', '失败']] : [])] as [Filter, string][]).map(([id, label]) => <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}{id !== 'all' ? <small>{counts[id]}</small> : null}</button>)}</nav><input className="queue-search" type="search" value={search} aria-label="搜索素材组" placeholder="搜索素材组" onChange={event => setSearch(event.target.value)} /></div>
        <div className="queue-table-head queue-grid"><input type="checkbox" aria-label="全选当前可处理组" disabled={busy || !selectable.length} checked={selectable.length > 0 && selectable.every(row => row.group.selected)} onChange={event => materials.selectQueueGroups(selectable.map(row => row.group.id), event.target.checked)} /><span>素材组</span><span>输入与配对</span><span>状态</span><span className="queue-output-cell">输出</span><span /></div>
        {!visible.length ? <div className="queue-empty">{rows.length ? '没有符合筛选条件的素材组。' : <><strong>导入第一组素材</strong><p>拖入音频或字幕，或使用下方导入与扫描。每组保留独立输入、状态与结果。</p></>}</div> : null}
        {visible.map((row, index) => <QueueGroupRow key={row.group.id} row={row} index={index} graph={graph} presetLabel={selectedPreset?.label ?? ''} busy={busy} discovering={discovering} batchAction={!!batchAction} recheck={paths => void resolvePaths(paths)} actOnBatch={(batch, action) => void actOnBatch(batch, action)} />)}
        <div className="queue-tail"><span>{rows.length} 个素材组 · {draftRows.filter(row => !row.issues.length).length} 组就绪 · {draftRows.filter(row => row.issues.length).length} 组需检查</span><span>按组保留输入与结果</span></div>
      </section>
      {historyError ? <div className="queue-notice" role="status">{historyError}<button type="button" onClick={() => void loadBatches()}>刷新状态</button></div> : null}{materialError ? <p className="queue-notice" role="status">{materialError}</p> : null}{requestError || workflow.error ? <p className="queue-error queue-notice" role="alert">{requestError || workflow.error}</p> : null}
      {materials.queueSubmission ? <div className="queue-notice" role="status"><span>{submitting ? '正在提交选中组…' : '有一笔提交结果待确认；将使用原请求编号核实。'}</span><button type="button" disabled={submitting} onClick={() => void recoverSubmission()}>核实提交结果</button></div> : null}{savedNotice ? <p className="queue-notice" role="status">{savedNotice}</p> : null}
      <div className="queue-destination"><span>▱ 输出位置</span><strong title={materials.outputDirectory || '工作区默认目录'}>{materials.outputDirectory || '工作区默认目录'} / 按素材组分目录</strong><button type="button" disabled={busy} onClick={() => void selectFolder().then(directory => { if (directory && active.current) materials.setOutputDirectory(directory) })}>更改</button>{materials.outputDirectory ? <button type="button" disabled={busy} onClick={() => materials.setOutputDirectory('')}>恢复默认</button> : null}</div>
    </div>
    {panelOpen ? <aside className="queue-parameter-panel" aria-label="本次运行参数"><div className="queue-panel-heading"><div><small>{selectedPreset?.label}</small><h2>本次运行参数</h2></div><button type="button" aria-label="关闭参数面板" onClick={() => setPanelOpen(false)}>×</button></div>
      <div className="queue-override-note"><span className="queue-count">{overrideCount} 个节点覆盖</span><p>仅用于下一次处理，原预设保持不变。<small>已运行与已完成的组不受影响。</small></p></div>
      <div className="queue-parameter-tabs" role="tablist" aria-label="参数分类"><button role="tab" type="button" aria-selected={parameterSection === 'common'} onClick={() => setParameterSection('common')}>常用参数</button><button role="tab" type="button" aria-selected={parameterSection === 'advanced'} onClick={() => setParameterSection('advanced')}>高级参数</button></div>
      <div className="queue-panel-scroll">{graph?.nodes.filter(node => parameterSection !== 'advanced' || graphNodeHasAdvancedParameters(node)).map((node, index) => <section className="queue-node-parameters" key={`${selectedPreset?.id}:${node.id}`}><h3><small>{String(index + 1).padStart(2, '0')}</small>{GRAPH_CATALOG[node.kind].label}<span>{node.id}</span></h3><GraphNodeParameters node={node} onChange={workflow.updateRuntimeNode} disabled={busy} section={parameterSection} /></section>)}
        {parameterSection === 'advanced' && !graph?.nodes.some(graphNodeHasAdvancedParameters) ? <p className="queue-muted">这条流水线没有额外高级参数。</p> : null}<section className="queue-panel-outputs"><h3>输出</h3>{graph?.outputs.map(output => <div key={`${output.node_id}:${output.port}`}><span>{output.label || (output.port === 'audio' ? '音频' : '字幕')}</span><small>{output.port === 'audio' ? '音频' : String(graph.nodes.find(node => node.id === output.node_id)?.options.subtitle_format || '字幕').toUpperCase()}</small></div>)}<p>产出类型由流水线定义。</p></section>
        {saveOpen ? <div className="queue-save-form"><label>新流水线名称<input value={copyName} disabled={busy} maxLength={100} onChange={event => setCopyName(event.target.value)} /></label><button type="button" disabled={busy || !copyName.trim()} onClick={() => void saveParameters('copy')}>保存为新流水线</button>{selectedPreset && !selectedPreset.builtin ? <button type="button" disabled={busy || !dirty} onClick={() => void saveParameters('update')}>保存参数到原预设</button> : <p>{selectedPreset ? '内置预设请另存修改。' : '原预设已移除；当前参数保留，请另存为新流水线。'}</p>}</div> : null}
      </div><div className="queue-panel-footer"><button type="button" disabled={busy} onClick={() => setSaveOpen(value => !value)}>另存为流水线</button><button type="button" className="queue-primary" onClick={() => setPanelOpen(false)}>完成调整</button></div>
    </aside> : null}</div>
    <footer className="queue-action-bar"><div className="queue-import-actions"><button type="button" disabled={busy || discovering} onClick={() => void chooseFiles()}>＋ 导入文件</button><button type="button" className="queue-link" disabled={busy || discovering} onClick={() => void chooseFolder()}>▱ 扫描文件夹</button><details className="queue-scan-settings"><summary>扫描设置</summary><label><input type="checkbox" checked={materials.scanRecursive} disabled={busy || discovering} onChange={event => materials.setScanRecursive(event.target.checked)} />扫描子文件夹</label>{materials.inputFolder ? <button type="button" title={materials.inputFolder} disabled={busy || discovering} onClick={() => void scanFolder(materials.inputFolder!)}>重新扫描</button> : null}</details>{discovering ? <small role="status">正在检查素材…</small> : null}</div><div className="queue-run-actions"><div className="queue-selection-summary"><strong>已勾选 {selected.length} 组</strong><span>{invalidSelected.length ? `${invalidSelected.length} 组需检查；全部就绪后才能运行` : selected.length ? '全部就绪 · 按当前参数提交' : '勾选需要处理的素材组'}</span></div><button type="button" className="queue-primary queue-start" disabled={busy || discovering || !!materials.queueSubmission || !selected.length || !!invalidSelected.length || !graph} onClick={() => void run()}>{submitting ? '正在提交…' : '▶ 开始处理'}<span>{selected.length} 组</span></button></div></footer>
  </div>
}
