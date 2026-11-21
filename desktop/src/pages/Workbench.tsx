import { t, format, useI18n } from '@/i18n'
import { confirmAction } from '@/utils/confirmAction'
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { ApiError } from '@/api/client'
import { batchesApi } from '@/api/batches'
import { inputsApi } from '@/api/inputs'
import type { GraphPresetDraft, GraphPresetItem, PresetItem } from '@/api/types'
import { usedGraphSlots } from '@/components/GraphRunBindings'
import QueueGroupRow from '@/components/tasks/QueueGroupRow'
import QuickStartHelp from '@/components/QuickStartHelp'
import StudioQuickStart from '@/components/StudioQuickStart'
import QueueRunParameters from '@/components/workflow/QueueRunParameters'
import { groupWorkflowPresets } from '@/domain/pipelinePreset'
import { groupEditable, groupIssues, type QueueSubmission } from '@/domain/queueGroups'
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
type Filter = 'all' | 'ready' | 'missing' | 'locked'

export default function Workbench() {
  useI18n()
  const materials = useWorkbenchStore(), workflow = useWorkflowStore()
  const { selectFiles, selectFolder } = useFileSelector()
  const { selectedPreset, runtimeGraph: graph } = workflow
  const presets = workflow.catalog.filter(isGraphPreset)
  const [mode, setMode] = useState<'studio' | 'queue'>('studio')
  const [panelOpen, setPanelOpen] = useState(false)
  const [parameterNodeId, setParameterNodeId] = useState('')
  const adjustButton = useRef<HTMLButtonElement>(null)
  const [filter, setFilter] = useState<Filter>('all'), [search, setSearch] = useState('')
  const [discovering, setDiscovering] = useState(false), [submitting, setSubmitting] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [materialError, setMaterialError] = useState(''), [requestError, setRequestError] = useState(''), [historyError, setHistoryError] = useState('')
  const [copyName, setCopyName] = useState(''), [savedNotice, setSavedNotice] = useState('')
  const active = useRef(true), importLock = useRef(false), submitLock = useRef(false), historySequence = useRef(0)
  const busy = submitting || workflow.saving
  const dirty = runtimeDirty(selectedPreset, graph)
  const changedNodes = useMemo(() => {
    if (!selectedPreset || !graph) return new Set<string>()
    const original = new Map(selectedPreset.graph.nodes.map(node => [node.id, draftFingerprint(node)]))
    return new Set(graph.nodes.filter(node => draftFingerprint(node) !== original.get(node.id)).map(node => node.id))
  }, [graph, selectedPreset])
  const panelActive = panelOpen && mode === 'queue' && Boolean(graph)
  const queueError = requestError || (!panelActive && workflow.error)
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
    const before = useWorkbenchStore.getState()
    const knownBatchIds = [...new Set([...before.queueBatches.map(batch => batch.batch_id),
      ...before.queueGroups.flatMap(group => group.run ? [group.run.batchId] : [])])]
    try {
      const result = await batchesApi.list()
      if (!active.current || sequence !== historySequence.current) return
      useWorkbenchStore.getState().reconcileQueueBatches(result.batches, knownBatchIds)
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
      const directory = window.prompt(t('浏览器模式无法读取完整路径，请输入这些文件所在目录：'))
      if (!directory) return
      paths = paths.map(path => /[\\/]/.test(path) ? path : `${directory}${directory.includes('/') ? '/' : '\\'}${path}`)
    }
    await resolvePaths(paths)
  }

  const rows = useMemo(() => materials.queueGroups.map(group => {
    const batch = group.run ? materials.queueBatches.find(batch => batch.batch_id === group.run!.batchId) : undefined
    const remote = batch?.items.find(item => item.item_id === group.run!.itemId)
    const issues = groupEditable(group) ? groupIssues(group, graph, materials.inputItems) : []
    const state = !groupEditable(group) ? group.pendingRequestId ? 'unknown' : group.run?.state ?? 'unknown'
      : group.excluded ? 'excluded' : issues.length ? 'missing' : 'draft'
    return { group, batch, remote, issues, state }
  }), [materials.queueGroups, materials.queueBatches, graph, materials.inputItems])
  const selectedMaterials = rows.filter(row => row.group.selected && groupEditable(row.group))
  const selected = selectedMaterials.filter(row => !row.group.excluded)
  const invalidSelected = selected.filter(row => row.issues.length > 0)
  const counts = { all: rows.length, ready: rows.filter(row => row.state === 'draft').length,
    missing: rows.filter(row => row.state === 'missing').length, locked: rows.filter(row => !groupEditable(row.group)).length }
  const visible = rows.filter(row => (filter === 'all' || filter === 'ready' && row.state === 'draft'
    || filter === 'missing' && row.state === 'missing' || filter === 'locked' && !groupEditable(row.group))
    && (!search.trim() || `${row.group.label} ${row.group.materialPaths.join(' ')}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())))
  const selectable = visible.filter(row => groupEditable(row.group))
  const removeMaterials = async (ids: string[]) => {
    if (busy || discovering) return
    const eligible = useWorkbenchStore.getState().queueGroups.filter(group => ids.includes(group.id) && groupEditable(group))
    if (!eligible.length || !await confirmAction(format('从素材目录删除 {0} 组素材引用？只移除本地目录中的这些组；磁盘音频、字幕和任务历史均保留。', [eligible.length]))) return
    useWorkbenchStore.getState().removeQueueMaterials(eligible.map(group => group.id))
  }

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
  const openEditor = async (preset: GraphPresetItem | null, useRuntime = false, draft?: GraphPresetDraft) => {
    if (busy) return
    if (editorDirty(workflow.editor) && !await confirmAction(t('存在未保存的流水线编辑草稿。打开此结构将替换该编辑草稿；工作台素材和本次参数会保留。继续？'))) return
    workflow.openEditor(preset, 'workbench', useRuntime)
    if (draft) workflow.updateEditor({ graph: draft.graph, label: draft.label, description: draft.description })
    await useNavStore.getState().setPage('workflow-presets')
  }
  const openStudioQueue = async (draft: GraphPresetDraft, paths: string[], folder?: string) => {
    if (busy || discovering) return
    if (draftFingerprint(draft.graph) !== draftFingerprint(graph)) {
      if (dirty && !await confirmAction(t('切换流水线会清除未保存的本次参数；素材组和已提交结果会保留。继续？'))) return
      workflow.useGraphForRun(draft.graph)
    }
    setCopyName(draft.label)
    setMode('queue')
    if (folder) {
      materials.setInputFolder(folder)
      await scanFolder(folder)
    }
    if (paths.length) await resolvePaths(paths)
  }
  const changePreset = async (id: string) => {
    const preset = presets.find(item => item.id === id)
    if (!preset || preset.id === selectedPreset?.id || busy) return
    if (dirty && !await confirmAction(t('切换流水线会清除未保存的本次参数；素材组和已提交结果会保留。继续？'))) return
    workflow.selectPreset(preset); setSavedNotice('')
  }
  const saveParameters = async (mode: 'update' | 'copy') => {
    if (busy || !graph) return false
    if (mode === 'update' && (!selectedPreset || !await confirmAction(format('将本次节点参数保存到“{0}”？', [selectedPreset.label])))) return false
    const saved = await workflow.saveRuntime(mode, mode === 'copy' ? copyName.trim() : undefined)
    if (saved && active.current) setSavedNotice(`已保存“${saved.label}”`)
    return Boolean(saved)
  }

  const closeParameters = () => {
    setPanelOpen(false)
    requestAnimationFrame(() => adjustButton.current?.focus({ preventScroll: true }))
  }

  return <div className={`queue-workbench${panelActive ? ' panel-open' : ''}${dragOver ? ' is-dragging' : ''}`} onDragOver={event => { event.preventDefault(); if (!busy && !discovering) setDragOver(true) }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragOver(false) }} onDrop={event => void drop(event)}>
    <header className="queue-page-heading page-heading app-page-heading">
      <div className="page-heading__copy">
        <div className="page-title-row">
          <h1 className="page-title">{t("创作台")}</h1>
          <QuickStartHelp topic="workbench" />
        </div>
      </div>
      <div className="page-heading__actions">
        <div role="tablist" aria-label={t("创作台模式")} style={{ display: 'inline-flex', background: 'var(--panel-muted)', padding: 3, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', gap: 2 }}>
          <button type="button" role="tab" aria-selected={mode === 'studio'} onClick={() => setMode('studio')} style={{ padding: '5px 12px', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600, background: mode === 'studio' ? 'var(--surface-elevated)' : 'transparent', color: mode === 'studio' ? 'var(--accent)' : 'var(--muted)', boxShadow: mode === 'studio' ? 'var(--shadow-xs)' : 'none' }}>{t("标准工作台")}</button>
          <button type="button" role="tab" aria-selected={mode === 'queue'} onClick={() => setMode('queue')} style={{ padding: '5px 12px', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600, background: mode === 'queue' ? 'var(--surface-elevated)' : 'transparent', color: mode === 'queue' ? 'var(--accent)' : 'var(--muted)', boxShadow: mode === 'queue' ? 'var(--shadow-xs)' : 'none' }}>{t("批量队列")}{rows.length ? ` · ${rows.length}` : ''}</button>
        </div>
      </div>
    </header>
    {mode === 'studio' ? (
      <StudioQuickStart
        onOpenBatchQueue={openStudioQueue}
        onOpenGraphEditor={draft => openEditor(null, false, draft)}
      />
    ) : <>
    <div className="queue-body"><div className="queue-pane">
      <div className="queue-preset-toolbar"><label>{t("流水线预设")}<select aria-label={t("已保存的流水线")} value={selectedPreset?.id ?? ''} disabled={busy || workflow.catalogLoading} onChange={event => changePreset(event.target.value)}>
        <option value="">{graph && !selectedPreset ? t("未保存流程") : workflow.catalogLoading ? t("正在加载流水线…") : presets.length ? t("请选择流水线") : t("暂无已保存流水线")}</option>
        {selectedPreset && !presets.some(preset => preset.id === selectedPreset.id) && <option value={selectedPreset.id}>{selectedPreset.label}{t("（等待目录核对）")}</option>}
        {groupWorkflowPresets(presets).map(group => <optgroup key={group.label} label={t(group.label)}>
          {group.items.map(preset => <option key={preset.id} value={preset.id}>{preset.label}{preset.builtin ? t(" · 内置") : ''}</option>)}
        </optgroup>)}
      </select></label>
        <button type="button" ref={adjustButton} className="queue-adjust" disabled={!graph} aria-expanded={panelActive} onClick={() => panelActive ? closeParameters() : setPanelOpen(true)}>{t("☷ 调整参数")}{changedNodes.size > 0 && <span className="queue-count" aria-label={format("{0} 个节点有临时覆盖", [changedNodes.size])}>{changedNodes.size}</span>}</button>
        <button type="button" className="queue-link" disabled={busy} onClick={() => openEditor(selectedPreset, true)}>{selectedPreset ? t("编辑流程 ↗") : graph ? t("编辑保留草稿 ↗") : t("新建流程 ↗")}</button>
      </div>
      {workflow.catalogError ? <div className="queue-notice" role="alert">{t(workflow.catalogError)}<button type="button" onClick={() => void workflow.loadCatalog()}>{t("重试加载")}</button></div> : null}
      {workflow.catalogNotice ? <div className="queue-draft-notice" role="status">{t(workflow.catalogNotice)}</div> : null}
      {!workflow.catalogLoading && !workflow.catalogError && !presets.length ? <div className="queue-draft-notice">{t("还没有流水线，可新建或添加内置模板。")}<button type="button" disabled={busy} onClick={() => useNavStore.getState().setPage('workflow-presets')}>{t("新建或添加模板")}</button></div> : null}
      {workflow.editor ? <div className="queue-draft-notice">{t("保留")}{editorDirty(workflow.editor) ? t("未保存的") : t("上次的")}{t("编辑草稿：")}{workflow.editor.label || t("未命名流水线")}<button type="button" disabled={busy} onClick={() => useNavStore.getState().setPage('workflow-presets')}>{t("继续编辑")}</button></div> : null}
      {materials.queueMigrationNotice ? <div className="queue-draft-notice">{t("素材草稿已保留，请检查输入并勾选运行。")}<button type="button" onClick={() => useWorkbenchStore.setState({ queueMigrationNotice: false })}>{t("知道了")}</button></div> : null}
      <section className="queue-section" aria-label={t("素材目录")}>
        <div className="queue-tools"><div className="queue-heading"><h2>{t("素材目录")}</h2><span className="queue-count">{rows.length}</span></div><nav className="queue-tabs" aria-label={t("素材筛选")}>{([['all', t("全部")], ['ready', t("可配置")], ['missing', t("需检查")], ['locked', t("暂时锁定")]] as [Filter, string][]).map(([id, label]) => <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}{id !== 'all' ? <small>{counts[id]}</small> : null}</button>)}</nav><input className="queue-search" type="search" value={search} aria-label={t("搜索素材组")} placeholder={t("搜索素材组")} onChange={event => setSearch(event.target.value)} /></div>
        <div className="queue-material-toolbar"><button type="button" className="queue-remove-material" disabled={busy || discovering || !selectedMaterials.length} onClick={() => removeMaterials(selectedMaterials.map(row => row.group.id))}>{t("删除所选素材（")}{selectedMaterials.length}）</button></div>
        <div className="queue-table-head queue-grid"><input type="checkbox" aria-label={t("全选当前可编辑素材")} disabled={busy || !selectable.length} checked={selectable.length > 0 && selectable.every(row => row.group.selected)} onChange={event => materials.selectQueueGroups(selectable.map(row => row.group.id), event.target.checked)} /><span>{t("素材组")}</span><span>{t("输入与配对")}</span><span>{t("素材状态")}</span><span className="queue-output-cell">{t("本次输出")}</span><span>{t("操作")}</span></div>
        {!visible.length ? <div className="queue-empty">{rows.length ? t("没有符合筛选条件的素材组。") : <><strong>{t("导入第一组素材")}</strong><p>{t("拖入音频或字幕，或使用下方导入与扫描。")}</p></>}</div> : null}
        {visible.map((row, index) => <QueueGroupRow key={row.group.id} row={row} index={index} graph={graph} presetLabel={selectedPreset?.label ?? ''} busy={busy} discovering={discovering} recheck={paths => void resolvePaths(paths)} removeMaterials={removeMaterials} />)}
      </section>
      {historyError ? <div className="queue-notice" role="status">{t(historyError)}<button type="button" onClick={() => void loadBatches()}>{t("刷新状态")}</button></div> : null}{materialError ? <p className="queue-notice" role="status">{t(materialError)}</p> : null}{queueError && <p className="queue-error queue-notice" role="alert">{t(queueError)}</p>}
      {materials.queueSubmission ? <div className="queue-notice" role="status"><span>{submitting ? t("正在提交选中组…") : t("有一笔提交结果待确认；将使用原请求编号核实。")}</span><button type="button" disabled={submitting} onClick={() => void recoverSubmission()}>{t("核实提交结果")}</button></div> : null}{savedNotice ? <p className="queue-notice queue-saved-notice" role="status">{t(savedNotice)}</p> : null}
    </div>
    {panelActive && graph && <QueueRunParameters key={selectedPreset?.id ?? 'draft'} graph={graph} preset={selectedPreset}
      selectedNodeId={parameterNodeId} onSelectNode={setParameterNodeId} changedNodes={changedNodes}
      busy={busy} error={workflow.error} saveStatus={savedNotice} onNodeChange={workflow.updateRuntimeNode}
      copyName={copyName} onCopyNameChange={setCopyName} onSave={saveParameters} onClose={closeParameters} />}
    </div>
    <footer className="queue-action-bar"><div className="queue-import-actions"><button type="button" disabled={busy || discovering} onClick={() => void chooseFiles()}>{t("＋ 导入文件")}</button><button type="button" className="queue-link" disabled={busy || discovering} onClick={() => void chooseFolder()}>{t("▱ 扫描文件夹")}</button><details className="queue-scan-settings"><summary>{t("扫描设置")}</summary><label><input type="checkbox" checked={materials.scanRecursive} disabled={busy || discovering} onChange={event => materials.setScanRecursive(event.target.checked)} />{t("扫描子文件夹")}</label>{materials.inputFolder ? <button type="button" title={materials.inputFolder} disabled={busy || discovering} onClick={() => void scanFolder(materials.inputFolder!)}>{t("重新扫描")}</button> : null}</details>{discovering ? <small role="status">{t("正在检查素材…")}</small> : null}</div><div className="queue-destination"><span>{t("▱ 输出位置")}</span><strong title={materials.outputDirectory || t("工作区默认目录")}>{materials.outputDirectory || t("工作区默认目录")}</strong><button type="button" disabled={busy} onClick={() => void selectFolder().then(directory => { if (directory && active.current) materials.setOutputDirectory(directory) })}>{t("更改")}</button>{materials.outputDirectory ? <button type="button" disabled={busy} onClick={() => materials.setOutputDirectory('')}>{t("恢复默认")}</button> : null}</div><div className="queue-run-actions">{invalidSelected.length ? <div className="queue-selection-summary"><span>{format("{0} 组需检查", [invalidSelected.length])}</span></div> : null}<button type="button" className="queue-primary queue-start" disabled={busy || discovering || !!materials.queueSubmission || !selected.length || !!invalidSelected.length || !graph} onClick={() => void run()}>{submitting ? t("正在提交…") : t("▶ 开始处理")}<span>{selected.length}  {t("组")}</span></button></div></footer>
    </>}
  </div>
}
