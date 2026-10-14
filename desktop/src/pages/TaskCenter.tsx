import QuickStartHelp from '@/components/QuickStartHelp'
import { t, format as formatMessage, useI18n } from '@/i18n'
import { useEffect, useLayoutEffect, useMemo, useState } from 'react'
import { tasksApi } from '@/api/tasks'
import { batchesApi } from '@/api/batches'
import { apiUrl } from '@/api/client'
import { confirmAction } from '@/utils/confirmAction'
import type { BatchRunResponse, TaskStatusResponse } from '@/api/types'
import BatchRunsPanel from '@/components/tasks/BatchRunsPanel'
import TaskRecoveryAction from '@/components/tasks/TaskRecoveryAction'
import TaskCenterDetails, { TaskStatusLabel, TaskSymbol } from '@/components/task-center/TaskCenterDetails'
import TaskDeletionDialog from '@/components/task-center/TaskDeletionDialog'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { useLogStore } from '@/stores/logStore'
import type { LogLevel } from '@/stores/logStore'
import { useNavStore } from '@/stores/navStore'
import { useTaskStore } from '@/stores/taskStore'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import type { JobType, Task, TaskStatus } from '@/stores/taskStore'
import { taskExecutionView } from '@/domain/taskExecutionView'
import type { TaskExecutionView } from '@/domain/taskExecutionView'
import { TASK_STATUS_GROUPS, TASK_STATUS_OPTIONS, taskMatchesStatusGroup, taskBatchMembership, taskPresentationEvents } from '@/domain/taskCenterPresentation'
import type { TaskStatusGroup } from '@/domain/taskCenterPresentation'
import './TaskCenter.css'

type TaskCategory = 'processing' | 'models' | 'tools'
type StatusFilter = { group: TaskStatusGroup; exact: TaskStatus | 'all' }
const TASK_CATEGORIES: Array<{ id: TaskCategory; label: string }> = [
  { id: 'processing', label: 'ASMR 处理' }, { id: 'models', label: '模型下载' }, { id: 'tools', label: '工具任务' },
]
function taskCategory(jobType: JobType): TaskCategory {
  return jobType === 'pipeline' ? 'processing' : jobType === 'model-install' ? 'models' : 'tools'
}
async function copyToClipboard(text: string) {
  try { await navigator.clipboard.writeText(text) } catch { window.prompt(t("复制路径"), text) }
}
function canSelectForDeletion(task: Task) {
  return !!task.serverTaskId && ['completed', 'failed', 'cancelled', 'skipped'].includes(task.status)
}

function TaskStatusPolling({ enabled }: { enabled: boolean }) {
  useTaskPolling(3000, enabled)
  return null
}

function stageLabel(task: Task, execution?: TaskExecutionView) {
  if (task.error?.code === 'TASK_INTERRUPTED') return t("任务已中断")
  if (task.jobType === 'reference-analyze' && !['completed', 'failed', 'cancelled', 'skipped'].includes(task.status)) {
    const stages: Record<string, string> = { reference_analysis: t("分析录音"), reference_read: t("读取录音"), reference_subtitles: t("检查已有字幕"), reference_separate: t("分离人声"), reference_decode: t("转换音频"), reference_transcribe: t("识别原文"), reference_segment: t("寻找片段"), reference_score: t("筛选片段") }
    return stages[task.stage || ''] || t("等待分析")
  }
  if (task.jobType !== 'pipeline') {
    if (task.status === 'completed') return t("任务已完成")
    if (task.status === 'failed') return formatMessage("任务在“{0}”阶段失败", [task.stage || t('执行')])
    if (task.status === 'cancelled') return t("任务已取消")
    if (task.status === 'skipped') return t("任务被跳过")
    return task.stage || t("等待执行")
  }
  return t((execution ?? taskExecutionView(task)).currentLabel)
}

function jobTypeLabel(jobType: JobType) {
  const labels: Record<JobType, string> = {
    pipeline: t("主流水线"),
    asr: 'ASR',
    tts: 'TTS',
    separate: t("人声分离"),
    convert: t("转换"),
    split: t("切分"),
    'translate-subtitle': t("字幕翻译"),
    'script-to-subtitle': t("Script 转 VTT"),
    'volume-preview': t("音量预览"),
    'model-install': t("模型安装"),
    'voice-design': t("音色设计"),
    'voice-clone': t("音色克隆"),
    'voice-preview': t("音色试听"),
    'speech-generate': t("配音候选生成"),
    'reference-analyze': t("录音片段分析"),
    unknown: t("历史任务"),
  }

  return labels[jobType] ?? jobType
}

export default function TaskCenter() {
  useI18n()
  const taskCenterView = useNavStore(state => state.taskCenterView)
  const setTaskCenterView = useNavStore(state => state.setTaskCenterView)
  const [pollGeneration, setPollGeneration] = useState(0)
  const tasks = useTaskStore(state => state.tasks)
  const selectedTaskId = useTaskStore(state => state.selectedTaskId)
  const selectTask = useTaskStore(state => state.selectTask)
  const addTask = useTaskStore(state => state.addTask)
  const updateTask = useTaskStore(state => state.updateTask)
  const removeDeletedTasks = useTaskStore(state => state.removeDeletedTasks)
  const selectedJobType = tasks.find(task => task.id === selectedTaskId)?.jobType
  const [category, setCategory] = useState<TaskCategory>(() => selectedJobType ? taskCategory(selectedJobType) : 'processing')
  const [categoryFilters, setCategoryFilters] = useState<Record<TaskCategory, StatusFilter>>({
    processing: { group: 'all', exact: 'all' }, models: { group: 'all', exact: 'all' }, tools: { group: 'all', exact: 'all' },
  })
  const filter = categoryFilters[category]
  const setFilter = (group: TaskStatusGroup) => setCategoryFilters(current => ({ ...current, [category]: { group, exact: 'all' } }))
  const setExactStatus = (exact: TaskStatus | 'all') => setCategoryFilters(current => ({ ...current, [category]: { ...current[category], exact } }))
  const [query, setQuery] = useState('')
  const [collapsedBatches, setCollapsedBatches] = useState<string[]>([])
  const [mobileDetail, setMobileDetail] = useState(false)
  const [batches, setBatches] = useState<BatchRunResponse[]>([])
  const [batchLoaded, setBatchLoaded] = useState(false)
  const [batchError, setBatchError] = useState('')
  const [checkedTaskIds, setCheckedTaskIds] = useState<string[]>([])
  const [deletionTaskIds, setDeletionTaskIds] = useState<string[] | null>(null)

  useLayoutEffect(() => {
    if (!selectedJobType) return
    const target = taskCategory(selectedJobType)
    setCategory(target)
    setMobileDetail(true)
  }, [selectedJobType, selectedTaskId])

  const logs = useLogStore(state => state.logs)
  const executionViews = useMemo(() => new Map(tasks.filter(task => task.jobType === 'pipeline')
    .map(task => [task.id, taskExecutionView(task, logs)])), [tasks, logs])
  const levelFilter = useLogStore(state => state.levelFilter)
  const setLevelFilter = useLogStore(state => state.setLevelFilter)
  const clearLogs = useLogStore(state => state.clearLogs)
  const addLog = useLogStore(state => state.addLog)
  const addRuntimeEvent = useLogStore(state => state.addRuntimeEvent)
  const showAudio = useAudioPlayerStore(state => state.show)
  const membership = useMemo(() => taskBatchMembership(tasks, batches), [tasks, batches])
  const categoryTasks = tasks.filter(task => taskCategory(task.jobType) === category)
    .slice().sort((a, b) => b.createdAt - a.createdAt || b.id.localeCompare(a.id))
  const search = query.trim().toLocaleLowerCase()
  // Counts and rows share the same category/search/exact-status scope; batch headings add no tasks.
  const statusScope = categoryTasks.filter(task => (filter.exact === 'all' || task.status === filter.exact)
    && (!search || [task.sourceName, task.id, task.serverTaskId, membership.get(task.id)?.name,
      membership.get(task.id)?.batch_id].join(' ').toLocaleLowerCase().includes(search)))
  const filteredTasks = statusScope.filter(task => taskMatchesStatusGroup(task.status, filter.group))
  // Browsing filters never silently switch the task whose details/actions are shown.
  const selectedTask = categoryTasks.find(task => task.id === selectedTaskId)
    ?? (selectedTaskId ? null : filteredTasks[0] ?? null)
  const selectedExecution = selectedTask ? executionViews.get(selectedTask.id) : undefined
  const visibleIds = new Set(filteredTasks.map(task => task.id))
  const runningTasks = categoryTasks.filter(task => task.status === 'running')
  const retryableFailedTasks = categoryTasks.filter(task => task.status === 'failed' && !task.historical)
  const taskLogs = selectedTask ? taskPresentationEvents(selectedTask, logs) : []
  const groupedBatches = batches.map(batch => ({ batch, children: filteredTasks.filter(task => membership.get(task.id)?.batch_id === batch.batch_id) }))
    .filter(group => group.children.length)
  const standalone = filteredTasks.filter(task => !membership.has(task.id))
  const selectableIds = [...new Set(filteredTasks.filter(canSelectForDeletion).map(task => task.serverTaskId!))]
  const checkedIds = checkedTaskIds.filter(id => tasks.some(task => task.serverTaskId === id))
  const allVisibleChecked = selectableIds.length > 0 && selectableIds.every(id => checkedIds.includes(id))
  const visibleSelectionTooLarge = new Set([...checkedIds, ...selectableIds]).size > 500
  const hiddenCheckedCount = checkedIds.filter(id => !filteredTasks.some(task => task.serverTaskId === id)).length
  const openDeletion = (ids: string[]) => { if (ids.length && ids.length <= 500) setDeletionTaskIds([...new Set(ids)]) }
  const handleDeleted = (ids: string[]) => {
    removeDeletedTasks(ids)
    useWorkbenchStore.getState().markQueueTaskHistoryDeleted(ids)
    setCheckedTaskIds(current => current.filter(id => !ids.includes(id)))
    setPollGeneration(value => value + 1)
  }
  const removeLocalFailure = async (task: Task) => {
    if (!await confirmAction(formatMessage("删除本地提交失败记录“{0}”？\n删除本次会话中的记录，无法撤销；不会取消或删除可能已经在服务端创建的任务，也不删除文件。", [task.sourceName]))) return
    useTaskStore.getState().removeLocalFailure(task.id)
  }
  const toggleChecked = (id: string) => setCheckedTaskIds(current => current.includes(id)
    ? current.filter(value => value !== id) : current.length < 500 ? [...current, id] : current)

  useEffect(() => {
    if (taskCenterView !== 'tasks') return
    let disposed = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      try {
        const response = await batchesApi.list()
        if (disposed) return
        setBatches(response.batches.slice().sort((a, b) => b.created_at.localeCompare(a.created_at)))
        setBatchLoaded(true)
        setBatchError('')
      } catch {
        if (!disposed) setBatchError("批次关联暂时无法刷新")
      }
      if (!disposed) timer = setTimeout(() => { void poll() }, 5000)
    }
    void poll()
    return () => { disposed = true; if (timer) clearTimeout(timer) }
  }, [taskCenterView])

  useEffect(() => {
    if (taskCenterView !== 'tasks') return
    if (!selectedTask?.serverTaskId) return
    return tasksApi.subscribeEvents(
      selectedTask.serverTaskId,
      (event) => { if (event.task_id === selectedTask.serverTaskId) addRuntimeEvent(event, selectedTask.id) },
    )
  }, [addRuntimeEvent, selectedTask?.id, selectedTask?.serverTaskId, taskCenterView])

  useEffect(() => {
    if (taskCenterView !== 'tasks') return
    if (!selectedTask?.serverTaskId) return
    if (selectedTask.specLoaded) return

    let cancelled = false
    tasksApi.spec(selectedTask.serverTaskId)
      .then((spec) => {
        if (cancelled) return
        if (spec.task_id !== selectedTask.serverTaskId) throw new Error("任务参数归属不匹配")
        updateTask(selectedTask.id, {
          params: spec.execution_profile,
          retryOfTaskId: spec.retry_of_task_id ?? undefined,
          specLoaded: true,
        })
      })
      .catch((error) => {
        if (!cancelled) {
          addLog({
            level: 'warn',
            content: `读取任务参数失败：${String(error)}`,
            taskId: selectedTask.id,
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [addLog, selectedTask?.id, selectedTask?.serverTaskId, selectedTask?.specLoaded, taskCenterView, updateTask])

  useEffect(() => {
    if (taskCenterView !== 'tasks') return
    if (!selectedTask?.serverTaskId) return
    if (selectedTask.status === 'pending' || selectedTask.status === 'running') return
    if (selectedTask.artifacts) return

    let cancelled = false
    tasksApi.result(selectedTask.serverTaskId)
      .then((response) => {
        if (cancelled) return
        if (response.task_id !== selectedTask.serverTaskId) throw new Error("任务产物归属不匹配")
        updateTask(selectedTask.id, {
          artifacts: {
            primaryArtifactId: response.primary_artifact_id ?? undefined,
            items: response.artifacts.filter(artifact => artifact.task_id === selectedTask.serverTaskId).map((artifact) => ({
              artifactId: artifact.artifact_id,
              type: artifact.type,
              path: artifact.path,
              stage: artifact.stage,
              label: artifact.label,
              primary: artifact.primary,
              preview: artifact.preview,
              metadata: artifact.metadata,
            })),
            warnings: response.warnings,
          },
        })
      })
      .catch((error) => {
        if (!cancelled) {
          addLog({
            level: 'warn',
            content: `读取历史产物失败：${String(error)}`,
            taskId: selectedTask.id,
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [
    addLog,
    selectedTask?.artifacts,
    selectedTask?.id,
    selectedTask?.serverTaskId,
    selectedTask?.status,
    taskCenterView,
    updateTask,
  ])

  const toggleLogLevel = (level: LogLevel) => {
    setLevelFilter(
      levelFilter.includes(level)
        ? levelFilter.filter((item) => item !== level)
        : [...levelFilter, level],
    )
  }

  const handleCancel = async (taskId: string) => {
    const task = tasks.find((item) => item.id === taskId)
    if (!task?.serverTaskId) {
      addLog({ level: 'warn', content: `任务尚未绑定后端 ID：${taskId}`, taskId })
      return
    }

    try {
      const response = await tasksApi.cancel(task.serverTaskId)
      updateTask(taskId, {
        status: response.state as TaskStatus,
        progress: Math.round(response.progress * 100),
        message: response.message || "已请求取消任务",
        detail: response.detail,
      })
      addLog({ level: 'info', content: `已请求取消任务：${task.serverTaskId}`, taskId })
    } catch (error) {
      addLog({ level: 'error', content: `取消失败：${String(error)}`, taskId })
    }
  }

  const handleRetry = async (taskId: string) => {
    const task = tasks.find((item) => item.id === taskId)
    if (!task?.serverTaskId) {
      addLog({ level: 'warn', content: `任务尚未绑定后端 ID：${taskId}`, taskId })
      return
    }
    if (task.historical) {
      addLog({
        level: 'warn',
        content: "历史任务仅用于查看；请从对应功能页面重新提交输入文件",
        taskId,
      })
      return
    }

    try {
      const response = await tasksApi.retry(task.serverTaskId)
      const newTaskId = addTask({
        serverTaskId: response.task_id,
        jobType: task.jobType,
        sourceName: task.sourceName,
        sourcePath: task.sourcePath,
        stage: response.stage ?? undefined,
        retryOfTaskId: response.retry_of_task_id ?? task.serverTaskId,
        historical: false,
        params: { ...task.params },
      })
      updateTask(newTaskId, {
        status: response.state as TaskStatus,
        progress: Math.round(response.progress * 100),
        message: response.message || "任务已重新排队",
        detail: response.detail,
        createdAt: Date.parse(response.created_at) || Date.now(),
      })
      setFilter('all')
      selectTask(newTaskId)
      addLog({ level: 'info', content: `已创建重试任务：${response.task_id}`, taskId: newTaskId })
    } catch (error) {
      addLog({ level: 'error', content: `重试失败：${String(error)}`, taskId })
    }
  }

  const handleRetryFailedTasks = async () => {
    for (const task of retryableFailedTasks) {
      await handleRetry(task.id)
    }
  }

  const handleResumed = (task: Task, response: TaskStatusResponse) => {
    const newTaskId = addTask({
      serverTaskId: response.task_id,
      jobType: task.jobType,
      sourceName: task.sourceName,
      sourcePath: task.sourcePath,
      stage: response.stage ?? undefined,
      retryOfTaskId: response.retry_of_task_id ?? task.serverTaskId,
      historical: false,
      params: { ...task.params },
    })
    updateTask(newTaskId, {
      status: response.state as TaskStatus,
      progress: Math.round(response.progress * 100),
      message: response.message || "任务已继续",
      detail: response.detail,
      createdAt: Date.parse(response.created_at) || Date.now(),
    })
    setFilter('all')
    selectTask(newTaskId)
    addLog({ level: 'info', content: `已创建恢复任务：${response.task_id}`, taskId: newTaskId })
  }

  const handleCancelRunningTasks = async () => {
    for (const task of runningTasks) {
      await handleCancel(task.id)
    }
  }

  const handlePlayArtifact = (artifactId: string, title: string) => {
    showAudio(apiUrl(`/artifacts/${encodeURIComponent(artifactId)}/file`), title)
  }

  const selectRow = (taskId: string) => { selectTask(taskId); setMobileDetail(true) }
  const row = (task: Task, child = false) => <div className="tc-selectable-row" key={task.id}>
    <input type="checkbox" aria-label={formatMessage("选择删除 {0}", [task.serverTaskId || task.id])}
      title={canSelectForDeletion(task) ? t("选择此任务历史") : t("运行中、待处理或尚未绑定后端的任务不可删除")}
      checked={!!task.serverTaskId && checkedIds.includes(task.serverTaskId)}
      disabled={!canSelectForDeletion(task) || (checkedIds.length >= 500 && !checkedIds.includes(task.serverTaskId!))}
      onChange={() => task.serverTaskId && toggleChecked(task.serverTaskId)} />
    <button type="button"
    className={`tc-task-row ${child ? 'is-child' : ''} ${selectedTask?.id === task.id ? 'is-selected' : ''}`}
    data-task-id={task.serverTaskId || task.id} aria-label={formatMessage("查看任务 {0}", [task.sourceName])}
    aria-pressed={selectedTask?.id === task.id} onClick={() => selectRow(task.id)}>
    <span className="tc-row-title"><span className="tc-file-symbol"><TaskSymbol name="file" /></span><span>
      <strong>{task.sourceName}</strong><small>{task.serverTaskId || task.id}</small>
      {task.jobType !== 'pipeline' && <span className="tc-row-progress">{stageLabel(task)} · {task.progress}%</span>}
    </span></span><TaskStatusLabel state={task.status} />
    <span className="tc-time"><time>{task.startedAt ? new Date(task.startedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : t("尚未开始")}</time>
      <small>{task.startedAt ? new Date(task.startedAt).toLocaleDateString([], { month: '2-digit', day: '2-digit' }) : '—'}</small></span>
  </button></div>

  return <div className={`task-center-page ${mobileDetail ? 'detail-open' : ''}`}>
    {/* Refresh restarts the existing serial poller; its cleanup discards older in-flight responses. */}
    <TaskStatusPolling key={pollGeneration} enabled={taskCenterView === 'tasks'} />
    <header className="tc-page-header page-heading"><div className="page-heading__copy"><div className="page-title-row"><h1 className="page-title">{t("任务中心")}</h1><QuickStartHelp topic={taskCenterView === 'batches' ? 'batches' : 'tasks'} /></div></div>
      <div className="tc-page-actions page-heading__actions"><button type="button" className="tc-action" aria-pressed={taskCenterView === 'tasks'} onClick={() => setTaskCenterView('tasks')}>{t("任务记录")}</button>
        <button type="button" className="tc-action" aria-pressed={taskCenterView === 'batches'} onClick={() => setTaskCenterView('batches')}>{t("批次管理")}</button>
        {taskCenterView === 'tasks' && <button type="button" className="tc-icon-button" aria-label={t("刷新任务状态")} onClick={() => setPollGeneration(value => value + 1)}><TaskSymbol name="refresh" /></button>}</div>
    </header>
    {taskCenterView === 'batches' ? <BatchRunsPanel /> : <>
      <div className="tc-category-toolbar"><label>{t("任务分类")}<select aria-label={t("任务分类")} value={category} onChange={event => { selectTask(null); setCategory(event.target.value as TaskCategory); setMobileDetail(false) }}>
        {TASK_CATEGORIES.map(item => <option key={item.id} value={item.id}>{t(item.label)} · {tasks.filter(task => taskCategory(task.jobType) === item.id).length}</option>)}</select></label>
        <details className="tc-bulk-actions"><summary>{t("批量操作")}</summary><div><button type="button" disabled={!retryableFailedTasks.length} onClick={() => void handleRetryFailedTasks()}>{t("重试本类失败任务 (")}{retryableFailedTasks.length})</button><button type="button" disabled={!runningTasks.length} onClick={() => void handleCancelRunningTasks()}>{t("取消本类运行任务 (")}{runningTasks.length})</button></div></details>
      </div>
      <div className="tc-toolbar"><nav className="tc-filters" aria-label={t("任务状态筛选")}>{TASK_STATUS_GROUPS.map(tab => <button key={tab.value} type="button" aria-pressed={filter.group === tab.value} onClick={() => setFilter(tab.value)}>
        {t(tab.label)}<small>{statusScope.filter(task => taskMatchesStatusGroup(task.status, tab.value)).length}</small></button>)}</nav>
        <details className="tc-status-detail"><summary>{t("精确状态")}{filter.exact !== 'all' && ` · ${t(TASK_STATUS_OPTIONS.find(option => option.value === filter.exact)?.label || '')}`}</summary>
          <label>{t("状态")}<select aria-label={t("精确任务状态")} value={filter.exact} onChange={event => setExactStatus(event.target.value as TaskStatus | 'all')}>
            <option value="all">{t("本组全部状态")}</option>{TASK_STATUS_OPTIONS.filter(option => taskMatchesStatusGroup(option.value, filter.group))
              .map(option => <option key={option.value} value={option.value}>{t(option.label)}</option>)}</select></label></details>
        <label className="tc-search"><TaskSymbol name="search" /><input aria-label={t("搜索任务名称或 ID")} placeholder={t("搜索任务名称或 ID")} value={query} onChange={event => setQuery(event.target.value)} /></label></div>
      {batchError && <p className="tc-refresh-error" role="status">{t(batchError)}</p>}
      <div className="tc-split"><section className="tc-list" aria-label={t("任务与批次列表")}>
        <div className="tc-selection-tools"><label><input type="checkbox" aria-label={t("选择当前筛选内可删除任务")}
          checked={allVisibleChecked} disabled={!selectableIds.length || (!allVisibleChecked && visibleSelectionTooLarge)}
          onChange={() => setCheckedTaskIds(current => allVisibleChecked ? current.filter(id => !selectableIds.includes(id)) : [...new Set([...current, ...selectableIds])])} />{t("当前列表")}</label>
          <span>{t("已选")}{checkedIds.length}{hiddenCheckedCount > 0 ? formatMessage("（筛选外 {0}）", [hiddenCheckedCount]) : ''}</span>
          <button type="button" className="tc-action" disabled={!checkedIds.length} onClick={() => openDeletion(checkedIds)}>{t("删除所选…")}</button>
          {!!checkedIds.length && <button type="button" className="tc-text-action" onClick={() => setCheckedTaskIds([])}>{t("清空选择")}</button>}
          {visibleSelectionTooLarge && <span>{t("每次最多选择 500 项，请缩小筛选或清空已有选择。")}</span>}
        </div>
        <div className="tc-table-heading"><span>{t("任务 / 批次")}</span><span>{t("状态")}</span><span>{t("开始时间")}</span></div>
        <div className="tc-list-scroll">{groupedBatches.map(({ batch, children }) => {
          const open = !collapsedBatches.includes(batch.batch_id) || !!search
          return <div className="tc-batch-group" key={batch.batch_id} data-batch-id={batch.batch_id}>
            <button className="tc-batch-row" type="button" aria-label={formatMessage("{0}批次 {1}", [t(open ? '收起' : '展开'), batch.name])} aria-expanded={open}
              onClick={() => setCollapsedBatches(current => current.includes(batch.batch_id) ? current.filter(id => id !== batch.batch_id) : [...current, batch.batch_id])}>
              <span className={`tc-chevron ${open ? 'open' : ''}`}><TaskSymbol name="chevron" /></span><TaskSymbol name="folder" /><span><strong>{batch.name}</strong><small>{batch.batch_id} · {batch.total_count} {t("组输入")}{batch.history_deleted_count ? formatMessage(" · 历史已删除 {0}", [batch.history_deleted_count]) : ''}</small></span>
              <span className="tc-batch-count">{batch.completed_count}/{Math.max(0, batch.total_count - (batch.history_deleted_count ?? 0))} {t("完成")}{batch.failed_count > 0 && <i>{t("含失败")}</i>}</span>
            </button>{open && children.map(task => row(task, true))}
          </div>
        })}
          {!!standalone.length && <div className="tc-section-label">{batchError ? t("任务（批次关联暂不可用）") : batchLoaded ? t("独立任务") : t("任务（正在读取批次关联）")}</div>}{standalone.map(task => row(task))}
          {!filteredTasks.length && <div className="tc-empty"><strong>{t("没有匹配的任务")}</strong><p>{t("尝试其他名称、ID 或状态。")}</p><button type="button" onClick={() => { setQuery(''); setFilter('all') }}>{t("清除筛选")}</button></div>}
        </div><footer className="tc-list-footer"><span>{t("显示")}{filteredTasks.length} {t("项任务 ·")}{groupedBatches.length} {t("个批次")}</span><span>{t("本地时间")}</span></footer>
      </section>
      <aside className="tc-detail" aria-label={t("所选任务详情")} data-selected-task={selectedTask?.serverTaskId || selectedTask?.id}>
        {selectedTask ? <TaskCenterDetails key={selectedTask.id} task={selectedTask} execution={selectedExecution} events={taskLogs}
          batchName={membership.get(selectedTask.id)?.name || (batchError ? t("批次关联未确认") : !batchLoaded ? t("正在读取批次关联") : undefined)} visible={visibleIds.has(selectedTask.id)} stage={stageLabel(selectedTask, selectedExecution)} jobLabel={jobTypeLabel(selectedTask.jobType)}
          onBack={() => setMobileDetail(false)} onPlay={handlePlayArtifact} onCopy={path => void copyToClipboard(path)} onConfigure={() => useNavStore.getState().openEngines('external')}
          levelFilter={levelFilter} onToggleLevel={toggleLogLevel} onClearLogs={clearLogs}
          actions={<><button type="button" className="tc-action" onClick={() => void handleRetry(selectedTask.id)} disabled={selectedTask.status !== 'failed' || selectedTask.historical}>{t("重试")}</button>
            <button type="button" className="tc-action" onClick={() => void handleCancel(selectedTask.id)} disabled={selectedTask.status !== 'running'}>{t("取消")}</button>
            <button type="button" className="tc-action" disabled={!canSelectForDeletion(selectedTask)}
              title={canSelectForDeletion(selectedTask) ? t("预览此任务的删除范围") : t("运行中或待处理任务不可删除")}
              onClick={() => selectedTask.serverTaskId && openDeletion([selectedTask.serverTaskId])}>{t("删除历史…")}</button>
            {!selectedTask.serverTaskId && selectedTask.status === 'failed' && <button type="button" className="tc-action" onClick={() => void removeLocalFailure(selectedTask)}>{t("删除本地记录…")}</button>}</>}
          recovery={selectedTask.serverTaskId && (selectedTask.status === 'failed' || selectedTask.status === 'cancelled')
            ? <div className="tc-recovery"><TaskRecoveryAction key={selectedTask.serverTaskId} taskId={selectedTask.serverTaskId} onResumed={response => handleResumed(selectedTask, response)} /></div> : null}
        /> : <div className="tc-empty">{t("请选择一项任务")}</div>}
      </aside></div>
    </>}
    {deletionTaskIds && <TaskDeletionDialog taskIds={deletionTaskIds} onDeleted={handleDeleted} onClose={() => setDeletionTaskIds(null)} />}
  </div>
}
