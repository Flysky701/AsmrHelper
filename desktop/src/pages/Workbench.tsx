import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { batchesApi } from '@/api/batches'
import { inputsApi } from '@/api/inputs'
import { pipelineApi } from '@/api/pipeline'
import { resourcesApi } from '@/api/resources'
import type { GraphPresetItem, PresetItem, TaskReadinessResponse } from '@/api/types'
import GraphRunBindings, { graphBindingIssues, usedGraphSlots } from '@/components/GraphRunBindings'
import GraphNodeParameters from '@/components/workflow/GraphNodeParameters'
import { GRAPH_CATALOG } from '@/domain/workflowGraph'
import { buildGraphRunRequest, editorDirty, runtimeDirty } from '@/domain/workflowDraft'
import { MAX_WORKBENCH_INPUTS, companionDescription, discoveredFileToInput, expandInputMaterials, fileName, inputPathKey, pathToInput, type WorkbenchInputItem } from '@/domain/workbenchInput'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { useNavStore } from '@/stores/navStore'
import { useTaskStore, type TaskStatus } from '@/stores/taskStore'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import { useWorkflowStore } from '@/stores/workflowStore'
import './Workbench.css'

const STATUS_LABELS: Record<TaskStatus, string> = { pending: '排队中', running: '执行中', completed: '已完成', failed: '失败', cancelled: '已取消', skipped: '已跳过' }
const extensions = new Set([...FILE_FILTERS.audio.extensions, ...FILE_FILTERS.subtitle.extensions])
const isGraphPreset = (preset: PresetItem | GraphPresetItem): preset is GraphPresetItem => 'version' in preset && preset.version === 2
const messageOf = (error: unknown) => error instanceof Error ? error.message : String(error)

export default function Workbench() {
  useTaskPolling(3000)
  const materials = useWorkbenchStore()
  const workflow = useWorkflowStore()
  const tasks = useTaskStore(state => state.tasks)
  const { selectFiles, selectFolder } = useFileSelector()
  const { catalog, selectedPreset, runtimeGraph: graph, bindings } = workflow
  const presets = catalog.filter(isGraphPreset)
  const legacyPresets = catalog.filter(preset => !isGraphPreset(preset))
  const [discovering, setDiscovering] = useState(false)
  const [materialError, setMaterialError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [checking, setChecking] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [requestError, setRequestError] = useState('')
  const [readiness, setReadiness] = useState<TaskReadinessResponse | null>(null)
  const [copyName, setCopyName] = useState('')
  const [savedNotice, setSavedNotice] = useState('')
  const [convertingPreset, setConvertingPreset] = useState<string | null>(null)
  const active = useRef(true)
  const operation = useRef(0)
  const checkSequence = useRef(0)
  const submitLock = useRef(false)
  const conversionLock = useRef(false)
  const busy = submitting || workflow.saving || convertingPreset !== null
  const dirty = runtimeDirty(selectedPreset, graph)
  const fingerprint = JSON.stringify({ graph, bindings, items: materials.inputItems, output: materials.outputDirectory })
  const currentFingerprint = useRef(fingerprint)
  currentFingerprint.current = fingerprint

  useEffect(() => {
    active.current = true
    void useWorkflowStore.getState().loadCatalog()
    return () => { active.current = false; operation.current += 1; checkSequence.current += 1 }
  }, [])
  useEffect(() => {
    const guard = () => {
      if (!submitLock.current && !conversionLock.current) return true
      setRequestError(submitLock.current ? '正在提交任务，请等待后端响应后再离开，避免重复创建。' : '正在转换旧版流水线，请等待读取完成后再离开。')
      return false
    }
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (submitLock.current || conversionLock.current) { event.preventDefault(); event.returnValue = '' }
    }
    useNavStore.getState().setNavigationGuard(guard)
    window.addEventListener('beforeunload', beforeUnload)
    return () => {
      if (useNavStore.getState().navigationGuard === guard) useNavStore.getState().setNavigationGuard(null)
      window.removeEventListener('beforeunload', beforeUnload)
    }
  }, [])
  useEffect(() => { checkSequence.current += 1; setReadiness(null); setChecking(false); setRequestError('') }, [fingerprint])
  useEffect(() => { setCopyName(selectedPreset ? `${selectedPreset.label} · 副本` : ''); setSavedNotice('') }, [selectedPreset?.id, selectedPreset?.revision])

  const localIssues = useMemo(() => graph ? graphBindingIssues(graph, bindings, materials.inputItems) : ['请选择一条已保存的流水线'], [graph, bindings, materials.inputItems])
  const usedSlots = graph ? usedGraphSlots(graph) : []
  const recentTasks = [...tasks].sort((left, right) => right.createdAt - left.createdAt).slice(0, 4)
  const boundCount = usedSlots.filter(slot => bindings[slot.id]?.path).length

  const appendItems = useCallback((items: WorkbenchInputItem[]) => {
    const current = useWorkbenchStore.getState().inputItems
    const existing = new Set(current.map(item => inputPathKey(item.path)))
    const expanded = expandInputMaterials(items)
    const updates = expanded.filter(item => existing.has(inputPathKey(item.path)))
    const incoming = expanded.filter(item => !existing.has(inputPathKey(item.path)))
    const room = Math.max(0, MAX_WORKBENCH_INPUTS - current.length)
    useWorkbenchStore.getState().addInputItems([...updates, ...incoming.slice(0, room)])
    if (incoming.length > room) setMaterialError(error => [error, `素材库最多 ${MAX_WORKBENCH_INPUTS} 项，其余 ${incoming.length - room} 项未加入。`].filter(Boolean).join(' '))
  }, [])

  const appendPaths = useCallback(async (paths: string[]) => {
    const unique = [...new Map(paths.map(path => [inputPathKey(path), path])).values()]
    const accepted = unique.filter(path => extensions.has(fileName(path).split('.').pop()?.toLowerCase() ?? ''))
    const rejected = unique.filter(path => !accepted.includes(path))
    setMaterialError(rejected.length ? `仅接受音频或 SRT / VTT / LRC 字幕，已忽略：${rejected.slice(0, 3).map(fileName).join('、')}` : '')
    const current = useWorkbenchStore.getState().inputItems
    const existing = new Set(current.map(item => inputPathKey(item.path)))
    let room = Math.max(0, MAX_WORKBENCH_INPUTS - current.length)
    const limited = accepted.filter(path => existing.has(inputPathKey(path)) || room-- > 0)
    if (limited.length < accepted.length) setMaterialError(error => [error, `素材库最多 ${MAX_WORKBENCH_INPUTS} 项，部分文件未加入。`].filter(Boolean).join(' '))
    if (!limited.length || !active.current) return
    const id = ++operation.current
    setDiscovering(true)
    try {
      const result = await inputsApi.resolveItems(limited)
      if (!active.current || id !== operation.current) return
      appendItems(result.items)
      if (result.warnings.length) setMaterialError(error => [error, ...result.warnings].filter(Boolean).join(' '))
    } catch (error) {
      if (!active.current || id !== operation.current) return
      appendItems(limited.filter(path => !existing.has(inputPathKey(path))).map(pathToInput))
      setMaterialError(`已保留所选路径，文件检查失败：${messageOf(error)}。运行前会再次检查。`)
    } finally { if (active.current && id === operation.current) setDiscovering(false) }
  }, [appendItems])

  const scanFolder = useCallback(async (directory: string) => {
    if (!active.current) return
    const id = ++operation.current
    setDiscovering(true); setMaterialError('')
    try {
      const result = await batchesApi.discover(directory, useWorkbenchStore.getState().scanRecursive, MAX_WORKBENCH_INPUTS + 1)
      if (!active.current || id !== operation.current) return
      appendItems(result.files.slice(0, MAX_WORKBENCH_INPUTS).map(discoveredFileToInput))
      if (result.files.length > MAX_WORKBENCH_INPUTS) setMaterialError(`仅载入排序后的前 ${MAX_WORKBENCH_INPUTS} 项。`)
    } catch (error) { if (active.current && id === operation.current) setMaterialError(`扫描失败：${messageOf(error)}`) }
    finally { if (active.current && id === operation.current) setDiscovering(false) }
  }, [appendItems])

  const chooseFiles = async () => {
    const paths = await selectFiles({ filters: [FILE_FILTERS.audio, FILE_FILTERS.subtitle] })
    if (active.current) await appendPaths(paths)
  }
  const chooseFolder = async () => {
    const directory = await selectFolder()
    if (directory && active.current) { materials.setInputFolder(directory); await scanFolder(directory) }
  }
  const drop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault(); setDragOver(false)
    if (busy || discovering) return
    const paths = Array.from(event.dataTransfer.files).map(file => (file as File & { path?: string }).path || file.name)
    if (!paths.length) return
    if (paths.some(path => !/[\\/]/.test(path))) {
      const directory = window.prompt('浏览器模式无法获取完整路径，请输入这些文件所在的目录：')
      if (!directory) return
      await appendPaths(paths.map(path => /[\\/]/.test(path) ? path : `${directory}${directory.includes('/') ? '/' : '\\'}${path}`))
    } else await appendPaths(paths)
  }

  const openEditor = (preset: GraphPresetItem | null, useRuntime = false) => {
    if (busy) return
    if (editorDirty(workflow.editor) && !window.confirm('仍有未保存的流水线编辑草稿。打开其他结构会替换该编辑草稿；工作台素材和本次参数会保留。继续？')) return
    workflow.openEditor(preset, 'workbench', useRuntime)
    useNavStore.getState().setPage('workflow-presets')
  }
  const convertLegacy = async (preset: PresetItem) => {
    if (busy || conversionLock.current) return
    if (editorDirty(workflow.editor) && !window.confirm('转换会替换尚未保存的编辑草稿；原预设和工作台素材仍会保留。继续？')) return
    conversionLock.current = true; setConvertingPreset(preset.id); setRequestError('')
    try {
      await workflow.openLegacyEditor(preset, 'workbench')
      const state = useWorkflowStore.getState()
      if (active.current && !state.error && state.editor) {
        conversionLock.current = false
        useNavStore.getState().setPage('workflow-presets')
      }
    } finally { conversionLock.current = false; if (active.current) setConvertingPreset(null) }
  }
  const changePreset = (id: string) => {
    const preset = presets.find(candidate => candidate.id === id)
    if (!preset || preset.id === selectedPreset?.id) return
    if (dirty && !window.confirm('切换流水线会放弃尚未保存的本次参数。素材草稿仍会保留。继续切换？')) return
    workflow.selectPreset(preset)
  }
  const saveParameters = async (mode: 'update' | 'copy') => {
    if (busy || !selectedPreset) return
    if (mode === 'update' && !window.confirm(`将本次节点参数保存到“${selectedPreset.label}”？以后选择它将使用这些参数。`)) return
    const saved = await workflow.saveRuntime(mode, mode === 'copy' ? copyName.trim() : undefined)
    if (saved && active.current) setSavedNotice(`已保存“${saved.label}”，素材绑定仍仅用于本次运行。`)
  }
  const makeRequest = () => {
    if (!graph) throw new Error('请先选择已保存的流水线')
    const issues = graphBindingIssues(graph, bindings, useWorkbenchStore.getState().inputItems)
    if (issues.length) throw new Error(issues.join('；'))
    return buildGraphRunRequest(graph, bindings, useWorkbenchStore.getState().inputItems.map(item => item.path), materials.outputDirectory)
  }
  const check = async (execute: boolean) => {
    if (submitLock.current || checking || discovering || busy) return
    if (execute) { submitLock.current = true; setSubmitting(true) }
    const key = currentFingerprint.current
    const id = ++checkSequence.current
    const isCurrent = () => active.current && id === checkSequence.current && key === currentFingerprint.current
    setRequestError(''); setReadiness(null); setChecking(true)
    try {
      const request = makeRequest()
      const result = await resourcesApi.checkTaskReadiness('pipeline', request.execution_profile, request.input.path)
      if (!isCurrent()) return
      setReadiness(result)
      if (!result.ready || !execute) return
      const response = await pipelineApi.createTask(request)
      const remote = response.task
      const taskStore = useTaskStore.getState()
      const taskId = taskStore.tasks.find(task => task.serverTaskId === remote.task_id)?.id ?? taskStore.addTask({
        jobType: 'pipeline', sourceName: `${selectedPreset?.label ?? '流水线'} · ${fileName(request.input.path)}`,
        sourcePath: request.input.path,
        params: { input_path: request.input.path, companion_paths: request.input.companion_paths ?? [], execution_profile: request.execution_profile, output_directory: materials.outputDirectory, workflow_preset_id: selectedPreset?.id, workflow_preset_revision: selectedPreset?.revision },
      })
      taskStore.updateTask(taskId, { serverTaskId: remote.task_id, status: remote.state as TaskStatus, stage: remote.stage ?? undefined, progress: Math.round(remote.progress * 100), message: remote.message || '后端已接管，等待执行', detail: remote.detail })
      if (isCurrent()) {
        submitLock.current = false
        taskStore.setFilter('all'); taskStore.selectTask(taskId)
        useNavStore.getState().openTaskCenter('tasks')
      }
    } catch (error) { if (isCurrent()) setRequestError(messageOf(error)) }
    finally {
      if (isCurrent()) setChecking(false)
      if (execute) { submitLock.current = false; if (active.current) setSubmitting(false) }
    }
  }

  return <main className="graph-workbench">
    <header className="graph-workbench-heading"><div><h1>工作台</h1><p>选择已保存的流水线，准备素材，调整本次运行参数。</p></div><button type="button" onClick={() => useNavStore.getState().openTaskCenter('tasks')}>任务与结果</button></header>
    <div className="graph-workbench-layout"><div className="graph-workbench-main">
      <section className="graph-workbench-section" aria-labelledby="workflow-preset-title">
        <div className="graph-workbench-section-heading"><h2 id="workflow-preset-title">流水线</h2><button type="button" disabled={busy} onClick={() => openEditor(null)}>新建流水线</button></div>
        {workflow.catalogLoading ? <p role="status">正在加载流水线…</p> : null}
        {workflow.catalogError ? <div role="alert">{workflow.catalogError} <button type="button" onClick={() => void workflow.loadCatalog()}>重试加载</button></div> : null}
        <label>已保存的流水线<select aria-label="已保存的流水线" value={selectedPreset?.id ?? ''} disabled={busy || workflow.catalogLoading} onChange={event => changePreset(event.target.value)}><option value="">请选择流水线</option>{selectedPreset && !presets.some(preset => preset.id === selectedPreset.id) ? <option value={selectedPreset.id}>{selectedPreset.label}（本地草稿，目录中已不可用）</option> : null}{presets.map(preset => <option key={preset.id} value={preset.id}>{preset.label}{preset.builtin ? ' · 内置' : ''}</option>)}</select></label>
        {selectedPreset ? <div className="graph-workbench-preset-caption"><p>{selectedPreset.description || '结构已保存。下方参数默认仅对本次运行生效。'}</p><button type="button" disabled={busy} onClick={() => openEditor(selectedPreset, true)}>编辑结构…</button></div> : <p className="graph-workbench-muted">{presets.length ? '选择后将显示输入槽、节点参数和产出。' : '还没有可运行的节点流水线。新建一条，或将旧版预设转换后检查并保存。'}</p>}
        {workflow.editor ? <div className="graph-workbench-preset-caption"><p className="graph-workbench-muted">保留了{editorDirty(workflow.editor) ? '未保存的' : '上次的'}编辑草稿：{workflow.editor.label || '未命名流水线'}</p><button type="button" disabled={busy} onClick={() => useNavStore.getState().setPage('workflow-presets')}>继续编辑草稿</button></div> : null}
        {legacyPresets.length ? <details className="graph-workbench-legacy"><summary>旧版步骤预设 · 转换后检查</summary><p>旧版预设缺少明确的素材槽和连线，不会直接运行。转换后请在编辑器确认。</p>{legacyPresets.map(preset => <button type="button" key={preset.id} disabled={busy} onClick={() => void convertLegacy(preset as PresetItem)}>{preset.label} · {convertingPreset === preset.id ? '正在转换…' : '转换'}</button>)}</details> : null}
        {workflow.error ? <p className="graph-workbench-error" role="alert">{workflow.error}</p> : null}
        {materials.flow.selectedStages.length ? <p className="graph-workbench-muted">原工作台素材、步骤草稿和声音参数仍保留；旧步骤开关不参与本次流水线运行。</p> : null}
        {graph ? <ol className="graph-workbench-structure" aria-label="流水线结构，只读">{graph.nodes.map(node => <li key={node.id}><strong>{GRAPH_CATALOG[node.kind].label}</strong><span>{node.id}</span></li>)}</ol> : null}
      </section>
      <section className="graph-workbench-section" aria-labelledby="workflow-input-title">
        <div className="graph-workbench-section-heading"><div><h2 id="workflow-input-title">输入素材</h2><p className="graph-workbench-muted">文件加入素材库后，再为输入槽明确选择；不会自动绑定或创建任务。</p></div><div className="graph-workbench-actions"><button type="button" disabled={busy || discovering} onClick={() => void chooseFiles()}>添加文件</button><button type="button" disabled={busy || discovering} onClick={() => void chooseFolder()}>扫描文件夹</button></div></div>
        <div className={`graph-workbench-drop${dragOver ? ' is-over' : ''}`} onDragOver={event => { event.preventDefault(); if (!busy && !discovering) setDragOver(true) }} onDragLeave={() => setDragOver(false)} onDrop={event => void drop(event)}>
          {discovering ? <p role="status">正在读取素材…</p> : <p>可拖入音频或 SRT / VTT / LRC 字幕</p>}
          {materials.inputItems.length ? <ul className="graph-workbench-materials">{materials.inputItems.map(item => <li key={item.path}><div><strong>{item.name}</strong><small title={item.path}>{item.path}</small><small>{companionDescription(item)}</small></div><button type="button" disabled={busy || discovering} aria-label={`移除 ${item.name}`} onClick={() => materials.removeInputItem(item.path)}>移除</button></li>)}</ul> : <p className="graph-workbench-muted">素材库为空</p>}
        </div>
        <div className="graph-workbench-folder"><label className="graph-workbench-checkbox"><input type="checkbox" checked={materials.scanRecursive} disabled={busy || discovering} onChange={event => materials.setScanRecursive(event.target.checked)} />扫描子文件夹</label>{materials.inputFolder ? <><span title={materials.inputFolder}>{materials.inputFolder}</span><button type="button" disabled={busy || discovering} onClick={() => void scanFolder(materials.inputFolder!)}>重新扫描</button></> : null}</div>
        {materialError ? <p className="graph-workbench-warning" role="status">{materialError}</p> : null}
        {graph ? <GraphRunBindings graph={graph} bindings={bindings} items={materials.inputItems} onChange={workflow.setBinding} disabled={busy} /> : null}
      </section>
      {graph ? <section className="graph-workbench-section" aria-labelledby="workflow-parameters-title">
        <div className="graph-workbench-section-heading"><div><h2 id="workflow-parameters-title">本次运行参数</h2><p className="graph-workbench-muted">按节点调整。节点与连线只能在流水线编辑页修改。</p></div><span className="graph-workbench-badge">{dirty ? '本次参数已修改 · 尚未保存' : '使用预设参数'}</span></div>
        {graph.nodes.map(node => <details className="graph-workbench-node" key={`${selectedPreset?.id}:${node.id}`}><summary><strong>{GRAPH_CATALOG[node.kind].label}</strong><span>{node.id} · {node.provider}{node.model ? ` / ${node.model}` : ''}</span><span>参数</span></summary><GraphNodeParameters node={node} onChange={workflow.updateRuntimeNode} disabled={busy} /></details>)}
        <div className="graph-workbench-save"><p>只有明确保存才会修改预设；素材绑定和输出目录不会写入预设。</p><div className="graph-workbench-actions">{selectedPreset && !selectedPreset.builtin ? <button type="button" disabled={busy || !dirty} onClick={() => void saveParameters('update')}>保存参数到此预设</button> : <span className="graph-workbench-muted">内置预设需另存后修改</span>}<label>另存名称<input aria-label="另存流水线名称" value={copyName} disabled={busy} maxLength={100} onChange={event => setCopyName(event.target.value)} /></label><button type="button" disabled={busy || !copyName.trim()} onClick={() => void saveParameters('copy')}>另存流水线</button></div></div>
        {savedNotice ? <p role="status">{savedNotice}</p> : null}
      </section> : null}
    </div>
    <aside className="graph-workbench-side"><section className="graph-workbench-section">
      <h2>本次运行</h2><dl className="graph-workbench-summary"><div><dt>流水线</dt><dd>{selectedPreset?.label ?? '未选择'}</dd></div><div><dt>输入槽</dt><dd>{boundCount} / {usedSlots.length} 已绑定</dd></div><div><dt>节点</dt><dd>{graph?.nodes.length ?? 0} 个 · 按依赖顺序执行</dd></div></dl><h3>产出</h3>{graph ? <ul className="graph-workbench-outputs">{graph.outputs.map(output => <li key={`${output.node_id}:${output.port}`}><strong>{output.label || (output.port === 'audio' ? '音频' : '字幕')}</strong><small>{output.node_id} · {output.port}</small></li>)}</ul> : <p className="graph-workbench-muted">选择流水线后显示</p>}<p className="graph-workbench-muted">产出由流水线定义；修改产出请进入编辑器。</p>
      <label>输出目录<button type="button" className="graph-workbench-output-path" disabled={busy} onClick={() => void selectFolder().then(directory => { if (directory && active.current) materials.setOutputDirectory(directory) })}>{materials.outputDirectory || '使用工作区默认目录'}</button></label>{materials.outputDirectory ? <button type="button" className="graph-workbench-link" disabled={busy} onClick={() => materials.setOutputDirectory('')}>恢复默认目录</button> : null}
      {localIssues.length ? <div className="graph-workbench-validation" role="status"><strong>运行前需要补充</strong><ul>{localIssues.map(issue => <li key={issue}>{issue}</li>)}</ul></div> : <p className="graph-workbench-muted">素材槽和结构已齐备，尚需检查文件及所选节点环境。</p>}
      {readiness ? <div className={readiness.ready ? 'graph-workbench-readiness' : 'graph-workbench-validation'} role="status"><strong>{readiness.ready ? '执行前检查通过 · 尚未运行' : '暂不可运行'}</strong>{readiness.issues.map((issue, index) => <p key={`${issue.stage}:${issue.code}:${index}`}>{issue.stage}：{issue.message}</p>)}{!readiness.ready && !readiness.issues.length ? <p>{readiness.missing_requirements.join('；') || '请检查所选节点的素材和运行环境'}</p> : null}</div> : null}
      {requestError ? <p className="graph-workbench-error" role="alert">{requestError}</p> : null}
      <div className="graph-workbench-run-actions"><button type="button" disabled={busy || checking || discovering || localIssues.length > 0} onClick={() => void check(false)}>{checking && !submitting ? '检查中…' : '检查执行条件'}</button><button type="button" className="graph-workbench-primary" disabled={busy || checking || discovering || localIssues.length > 0} onClick={() => void check(true)}>{submitting ? '正在提交…' : '运行一次'}</button></div><p className="graph-workbench-muted">本次只创建一个图任务，不会将多个素材自动展开为批量任务。历史批次可在任务中心查看。</p>
    </section><section className="graph-workbench-section"><div className="graph-workbench-section-heading"><h2>最近任务</h2><button type="button" onClick={() => useNavStore.getState().openTaskCenter('tasks')}>全部</button></div>{recentTasks.length ? <div className="graph-workbench-recent">{recentTasks.map(task => <button type="button" key={task.id} onClick={() => { const store = useTaskStore.getState(); store.setFilter('all'); store.selectTask(task.id); useNavStore.getState().openTaskCenter('tasks') }}><strong>{task.sourceName}</strong><small>{task.serverTaskId ?? task.id} · {STATUS_LABELS[task.status]}</small><small>{new Date(task.createdAt).toLocaleString()}</small></button>)}</div> : <p className="graph-workbench-muted">还没有任务记录。</p>}</section></aside>
    </div>
  </main>
}
