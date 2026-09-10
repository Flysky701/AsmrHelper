import { useEffect } from 'react'
import type { CSSProperties, ReactNode } from 'react'

import { tasksApi } from '@/api/tasks'
import { apiUrl } from '@/api/client'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { useLogStore } from '@/stores/logStore'
import type { LogLevel } from '@/stores/logStore'
import { useNavStore } from '@/stores/navStore'
import { useTaskStore } from '@/stores/taskStore'
import type { JobType, Task, TaskStatus } from '@/stores/taskStore'

const STATUS_CONFIG: Record<TaskStatus, { label: string; dot: string; bg: string; color: string }> = {
  running: { label: '运行中', dot: 'var(--accent)', bg: 'var(--accent-soft)', color: 'var(--accent)' },
  pending: { label: '排队中', dot: 'var(--muted)', bg: 'var(--panel-muted)', color: 'var(--muted-strong)' },
  completed: { label: '已完成', dot: 'var(--success)', bg: 'var(--success-soft)', color: 'var(--success)' },
  failed: { label: '失败', dot: 'var(--error)', bg: 'var(--error-soft)', color: 'var(--error)' },
  cancelled: { label: '已取消', dot: 'var(--muted)', bg: 'var(--panel-muted)', color: 'var(--muted-strong)' },
  skipped: { label: '已跳过', dot: 'var(--warning)', bg: 'var(--warning-soft)', color: 'var(--warning)' },
}

const PIPELINE_STAGES = ['准备', '人声分离', 'ASR 识别', '字幕翻译', 'TTS 合成', '混音输出', '导出产物'] as const
const PIPELINE_STAGE_INDEX: Record<string, number> = {
  prepare: 0,
  separate: 1,
  asr: 2,
  translate: 3,
  tts: 4,
  mix: 5,
  export: 6,
}

const SURFACE_STYLE: CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-panel)',
}

const TASK_CENTER_LAYOUT_STYLES = `
  .task-center-page {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .task-center-header {
    padding: 22px 28px 18px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    display: flex;
    gap: 18px;
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .task-center-header-copy {
    flex: 1 1 420px;
    min-width: 0;
  }

  .task-center-toolbar {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-left: auto;
  }

  .task-center-toolbar-button {
    white-space: nowrap;
  }

  .task-center-stats {
    width: 100%;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr));
    gap: 12px;
  }

  .task-center-content {
    display: grid;
    grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
    gap: 20px;
    flex: 1;
    min-height: 0;
    padding: 20px;
  }

  .task-center-list-panel {
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .task-center-task-list {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 14px;
    display: grid;
    gap: 12px;
    align-content: start;
    grid-auto-rows: max-content;
  }

  .task-center-list-panel > :not(.task-center-task-list) {
    flex: 0 0 auto;
  }

  .task-center-task-card {
    align-self: start;
    min-height: 122px;
  }

  .task-center-task-summary {
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-height: 1.45;
  }

  .task-center-detail {
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-width: 0;
    min-height: 0;
    overflow: auto;
    padding-right: 4px;
  }

  .task-center-detail > * {
    flex: 0 0 auto;
  }

  .task-center-detail-pair {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
    gap: 16px;
  }

  .task-center-break-anywhere {
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  @media (max-width: 1100px) {
    .task-center-page {
      overflow: auto;
    }

    .task-center-content {
      grid-template-columns: minmax(0, 1fr);
      flex: none;
      min-height: auto;
      padding: 16px;
    }

    .task-center-list-panel {
      min-height: 320px;
      max-height: min(48vh, 520px);
    }

    .task-center-detail {
      overflow: visible;
      padding-right: 0;
    }
  }

  @media (max-width: 680px) {
    .task-center-header {
      padding: 18px 16px 14px;
      gap: 14px;
    }

    .task-center-header-copy {
      flex-basis: 100%;
    }

    .task-center-toolbar {
      width: 100%;
      margin-left: 0;
    }

    .task-center-toolbar > button {
      flex: 1 1 150px;
    }

    .task-center-stats {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }

    .task-center-stats > div {
      padding: 11px 12px !important;
    }

    .task-center-content {
      gap: 14px;
      padding: 12px;
    }

    .task-center-list-panel {
      min-height: 300px;
      max-height: 420px;
    }
  }
`

type FilterValue = 'all' | TaskStatus

const FILTER_TABS: { value: FilterValue; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'pending', label: '排队' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
  { value: 'skipped', label: '已跳过' },
]

const LOG_LEVELS: { value: LogLevel; label: string }[] = [
  { value: 'info', label: 'INFO' },
  { value: 'warn', label: 'WARN' },
  { value: 'error', label: 'ERROR' },
]

function StatusPill({ status }: { status: TaskStatus }) {
  const config = STATUS_CONFIG[status]

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 10px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        background: config.bg,
        color: config.color,
        flexShrink: 0,
      }}
    >
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: config.dot }} />
      {config.label}
    </span>
  )
}

function ToolbarButton({
  children,
  onClick,
  disabled,
  variant = 'secondary',
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  variant?: 'primary' | 'secondary' | 'ghost'
}) {
  const variants: Record<string, CSSProperties> = {
    primary: {
      background: 'var(--accent)',
      color: 'white',
      border: '1px solid var(--accent)',
      boxShadow: 'var(--shadow-float)',
    },
    secondary: {
      background: 'var(--surface)',
      color: 'var(--fg)',
      border: '1px solid var(--border)',
    },
    ghost: {
      background: 'transparent',
      color: 'var(--muted)',
      border: '1px solid transparent',
    },
  }

  return (
    <button
      className="task-center-toolbar-button"
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        minHeight: 36,
        padding: '0 14px',
        borderRadius: 'var(--radius-button)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        fontSize: 13,
        fontWeight: 600,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        ...variants[variant],
      }}
    >
      {children}
    </button>
  )
}

function formatRelativeTime(timestamp: number) {
  const delta = Math.max(0, Date.now() - timestamp)
  const minutes = Math.floor(delta / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

function formatDateTime(timestamp?: number) {
  if (!timestamp) return '—'
  return new Date(timestamp).toLocaleString()
}

function formatDuration(durationMs?: number) {
  if (!durationMs || durationMs <= 0) return '—'
  const totalSeconds = Math.floor(durationMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes === 0) return `${seconds}s`
  return `${minutes}m ${seconds}s`
}

function pipelineStageIndex(task: Task): number {
  if (task.stage && task.stage in PIPELINE_STAGE_INDEX) return PIPELINE_STAGE_INDEX[task.stage] ?? 0
  if (task.status === 'completed') return PIPELINE_STAGES.length - 1
  return 0
}

function shouldSuggestProviderVerification(task: Task): boolean {
  if (task.status !== 'failed') return false
  const action = typeof task.error?.action === 'string' ? task.error.action : ''
  const code = typeof task.error?.code === 'string' ? task.error.code : ''
  return action === 'settings' || code === 'PROVIDER_EXECUTION_FAILED'
}

function stageLabel(task: Task) {
  if (task.jobType !== 'pipeline') {
    if (task.status === 'completed') return '任务已完成'
    if (task.status === 'failed') return `任务在“${task.stage || '执行'}”阶段失败`
    if (task.status === 'cancelled') return '任务已取消'
    if (task.status === 'skipped') return '任务被跳过'
    return task.stage || '等待执行'
  }
  if (task.status === 'completed') return '成品已产出'
  const currentStage = PIPELINE_STAGES[pipelineStageIndex(task)] ?? '准备'
  if (task.status === 'failed') return `任务在“${currentStage}”阶段失败`
  if (task.status === 'cancelled') return '任务已取消'
  if (task.status === 'skipped') return '任务被跳过'
  return currentStage
}

function jobTypeLabel(jobType: JobType) {
  const labels: Record<JobType, string> = {
    pipeline: '主流水线',
    asr: 'ASR',
    tts: 'TTS',
    separate: '人声分离',
    convert: '转换',
    split: '切分',
    'translate-subtitle': '字幕翻译',
    'script-to-subtitle': 'Script 转 VTT',
    'volume-preview': '音量预览',
    'model-install': '模型安装',
    'voice-design': '音色设计',
    'voice-clone': '音色克隆',
    'voice-preview': '音色试听',
    unknown: '历史任务',
  }

  return labels[jobType] ?? jobType
}

function paramLabel(key: string) {
  const labels: Record<string, string> = {
    input_path: '输入文件',
    source_lang: '源语言',
    target_lang: '目标语言',
    use_vocal_separator: '人声分离',
    tts_engine: 'TTS 引擎',
    tts_voice: 'TTS 声线',
    vocal_model: '分离模型',
    asr_model: 'ASR 模型',
    translate_provider: '翻译提供方',
    tts_speed: '语速',
    original_volume: '原声保留',
    tts_volume_ratio: 'TTS 音量占比',
    tts_delay: 'TTS 延迟',
    skip_existing: '跳过已有输出',
    voice_profile_id: '音色档案',
  }

  return labels[key] ?? key
}

function formatParamValue(value: unknown) {
  if (typeof value === 'boolean') return value ? '开启' : '关闭'
  if (typeof value === 'number') return Number.isInteger(value) ? `${value}` : value.toFixed(2)
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    window.prompt('复制路径', text)
  }
}

function PipelineTimeline({ task }: { task: Task }) {
  const activeIndex = pipelineStageIndex(task)
  const isFailed = task.status === 'failed'

  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {PIPELINE_STAGES.map((stage, index) => {
        const completed = task.status === 'completed' || index < activeIndex
        const active = task.status === 'running' && index === activeIndex
        const failed = isFailed && index === activeIndex

        return (
          <div key={stage} style={{ display: 'grid', gridTemplateColumns: '26px minmax(0, 1fr)', gap: 12 }}>
            <div
              style={{
                width: 26,
                height: 26,
                borderRadius: 999,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 12,
                fontWeight: 700,
                border: '1px solid var(--border)',
                background: completed ? 'var(--success-soft)' : active ? 'var(--accent-soft)' : failed ? 'var(--error-soft)' : 'var(--panel-muted)',
                color: completed ? 'var(--success)' : active ? 'var(--accent)' : failed ? 'var(--error)' : 'var(--muted)',
              }}
            >
              {index + 1}
            </div>
            <div style={{ paddingTop: 2 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{stage}</div>
              <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>
                {completed ? '阶段已完成' : active ? '当前进行中' : failed ? '在这里失败' : '等待执行'}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function TaskCenter() {
  useTaskPolling(3000)

  const tasks = useTaskStore((state) => state.tasks)
  const filter = useTaskStore((state) => state.filter)
  const setFilter = useTaskStore((state) => state.setFilter)
  const selectedTaskId = useTaskStore((state) => state.selectedTaskId)
  const selectTask = useTaskStore((state) => state.selectTask)
  const addTask = useTaskStore((state) => state.addTask)
  const updateTask = useTaskStore((state) => state.updateTask)
  const setPage = useNavStore((state) => state.setPage)

  const logs = useLogStore((state) => state.logs)
  const levelFilter = useLogStore((state) => state.levelFilter)
  const setLevelFilter = useLogStore((state) => state.setLevelFilter)
  const clearLogs = useLogStore((state) => state.clearLogs)
  const addLog = useLogStore((state) => state.addLog)
  const addRuntimeEvent = useLogStore((state) => state.addRuntimeEvent)

  const showAudio = useAudioPlayerStore((state) => state.show)

  const filteredTasks = filter === 'all' ? tasks : tasks.filter((task) => task.status === filter)
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? filteredTasks[0] ?? null

  const runningTasks = tasks.filter((task) => task.status === 'running')
  const pendingTasks = tasks.filter((task) => task.status === 'pending')
  const failedTasks = tasks.filter((task) => task.status === 'failed')
  const retryableFailedTasks = failedTasks.filter((task) => !task.historical)
  const completedTasks = tasks.filter((task) => task.status === 'completed')

  const taskLogs = selectedTask ? logs.filter((entry) => entry.taskId === selectedTask.id) : logs
  const filteredLogs = taskLogs.filter((entry) => levelFilter.includes(entry.level)).slice(-120).reverse()

  const artifacts = selectedTask?.artifacts?.items ?? []

  useEffect(() => {
    if (!selectedTask?.serverTaskId) return
    return tasksApi.subscribeEvents(
      selectedTask.serverTaskId,
      (event) => addRuntimeEvent(event, selectedTask.id),
    )
  }, [addRuntimeEvent, selectedTask?.id, selectedTask?.serverTaskId])

  useEffect(() => {
    if (!selectedTask?.serverTaskId) return
    if (selectedTask.specLoaded) return

    let cancelled = false
    tasksApi.spec(selectedTask.serverTaskId)
      .then((spec) => {
        if (cancelled) return
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
  }, [addLog, selectedTask?.id, selectedTask?.serverTaskId, selectedTask?.specLoaded, updateTask])

  useEffect(() => {
    if (!selectedTask?.serverTaskId) return
    if (selectedTask.status === 'pending' || selectedTask.status === 'running') return
    if (selectedTask.artifacts) return

    let cancelled = false
    tasksApi.result(selectedTask.serverTaskId)
      .then((response) => {
        if (cancelled) return
        updateTask(selectedTask.id, {
          artifacts: {
            primaryArtifactId: response.primary_artifact_id ?? undefined,
            items: response.artifacts.map((artifact) => ({
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
        message: response.message || '已请求取消任务',
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
        content: '历史任务仅用于查看；请从对应功能页面重新提交输入文件',
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
        message: response.message || '任务已重新排队',
        detail: response.detail,
        createdAt: Date.parse(response.created_at) || Date.now(),
      })
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

  const handleCancelRunningTasks = async () => {
    for (const task of runningTasks) {
      await handleCancel(task.id)
    }
  }

  const handlePlayArtifact = (artifactId: string, title: string) => {
    showAudio(apiUrl(`/artifacts/${encodeURIComponent(artifactId)}/file`), title)
  }

  return (
    <div className="task-center-page">
      <style>{TASK_CENTER_LAYOUT_STYLES}</style>
      <header className="task-center-header">
        <div className="task-center-header-copy">
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Task Cockpit
          </div>
          <h1 style={{ marginTop: 8, fontSize: 26, lineHeight: 1.15, fontWeight: 700, fontFamily: 'var(--font-display)' }}>
            任务中心
          </h1>
          <p style={{ marginTop: 8, color: 'var(--muted)', maxWidth: 560 }}>
            这里负责跟踪阶段、查看产物、处理失败任务。日志保留，但退到详情区。
          </p>
        </div>

        <div className="task-center-toolbar">
          <ToolbarButton variant="secondary" onClick={handleRetryFailedTasks} disabled={retryableFailedTasks.length === 0}>
            重试失败任务
          </ToolbarButton>
          <ToolbarButton variant="secondary" onClick={handleCancelRunningTasks} disabled={runningTasks.length === 0}>
            取消运行中
          </ToolbarButton>
        </div>

        <div className="task-center-stats">
          {[
            { label: '运行中', value: runningTasks.length, background: 'var(--accent-soft)', color: 'var(--accent)' },
            { label: '排队中', value: pendingTasks.length, background: 'var(--panel-muted)', color: 'var(--muted-strong)' },
            { label: '失败', value: failedTasks.length, background: 'var(--error-soft)', color: 'var(--error)' },
            { label: '已完成', value: completedTasks.length, background: 'var(--success-soft)', color: 'var(--success)' },
          ].map((item) => (
            <div key={item.label} style={{ ...SURFACE_STYLE, padding: '14px 16px' }}>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>{item.label}</div>
              <div style={{ marginTop: 6, fontSize: 22, fontWeight: 700, color: item.color }}>{item.value}</div>
            </div>
          ))}
        </div>
      </header>

      <div className="task-center-content">
        <section className="task-center-list-panel" style={SURFACE_STYLE}>
          <div style={{ padding: '16px 18px 14px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>任务列表</div>
            <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>
              优先看状态、阶段和可操作的产物入口。
            </div>
          </div>

          <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {FILTER_TABS.map((tab) => {
              const count = tab.value === 'all'
                ? tasks.length
                : tasks.filter((task) => task.status === tab.value).length

              return (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => setFilter(tab.value)}
                  style={{
                    padding: '7px 10px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border)',
                    background: filter === tab.value ? 'var(--accent-soft)' : 'var(--surface)',
                    color: filter === tab.value ? 'var(--accent)' : 'var(--muted-strong)',
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  {tab.label} <span style={{ opacity: 0.72 }}>{count}</span>
                </button>
              )
            })}
          </div>

          <div className="task-center-task-list">
            {filteredTasks.length === 0 ? (
              <div style={{ display: 'grid', placeItems: 'center', minHeight: 240, color: 'var(--muted)' }}>
                当前筛选条件下还没有任务。
              </div>
            ) : (
              filteredTasks
                .slice()
                .reverse()
                .map((task) => {
                  const isSelected = selectedTask?.id === task.id
                  const primaryOutput = task.artifacts?.items.find(
                    (artifact) => artifact.artifactId === task.artifacts?.primaryArtifactId,
                  )?.path

                  return (
                    <button
                      key={task.id}
                      type="button"
                      className="task-center-task-card"
                      onClick={() => selectTask(task.id)}
                      style={{
                        width: '100%',
                        minWidth: 0,
                        textAlign: 'left',
                        padding: '14px 14px 12px',
                        borderRadius: 'var(--radius-card)',
                        border: isSelected ? '1px solid var(--accent)' : '1px solid var(--border)',
                        background: isSelected ? 'var(--accent-soft)' : 'var(--surface)',
                        cursor: 'pointer',
                        boxShadow: isSelected ? 'var(--shadow-float)' : 'none',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {task.sourceName}
                          </div>
                          <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>
                            {jobTypeLabel(task.jobType)} · {formatRelativeTime(task.createdAt)}
                          </div>
                        </div>
                        <StatusPill status={task.status} />
                      </div>

                      <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
                        <div style={{ fontSize: 12, color: 'var(--muted)' }}>当前阶段：{stageLabel(task)}</div>
                        <div style={{ height: 6, borderRadius: 999, background: 'var(--panel-muted)', overflow: 'hidden' }}>
                          <div
                            style={{
                              width: `${Math.max(0, Math.min(100, task.progress))}%`,
                              height: '100%',
                              background: task.status === 'failed' ? 'var(--error)' : task.status === 'completed' ? 'var(--success)' : 'var(--accent)',
                              borderRadius: 999,
                            }}
                          />
                        </div>
                        <div className="task-center-task-summary task-center-break-anywhere" style={{ fontSize: 12, color: 'var(--muted)' }}>
                          {task.message || '等待阶段消息'}
                        </div>
                        {primaryOutput ? (
                          <div style={{ fontSize: 12, color: 'var(--fg)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            主要产物：{primaryOutput}
                          </div>
                        ) : null}
                      </div>
                    </button>
                  )
                })
            )}
          </div>
        </section>

        <section className="task-center-detail">
          {!selectedTask ? (
            <div style={{ ...SURFACE_STYLE, minHeight: 360, display: 'grid', placeItems: 'center', color: 'var(--muted)' }}>
              选择一个任务查看阶段、产物和日志。
            </div>
          ) : (
            <>
              <div style={{ ...SURFACE_STYLE, padding: '18px 20px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                  <div style={{ minWidth: 0, flex: '1 1 260px' }}>
                    <div style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-display)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {selectedTask.sourceName}
                    </div>
                    <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      <StatusPill status={selectedTask.status} />
                      <span style={{ fontSize: 12, color: 'var(--muted)' }}>{jobTypeLabel(selectedTask.jobType)}</span>
                      <span style={{ fontSize: 12, color: 'var(--muted)' }}>创建于 {formatDateTime(selectedTask.createdAt)}</span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <ToolbarButton
                      variant="secondary"
                      onClick={() => handleRetry(selectedTask.id)}
                      disabled={selectedTask.status !== 'failed' || selectedTask.historical}
                    >
                      重试
                    </ToolbarButton>
                    <ToolbarButton
                      variant="secondary"
                      onClick={() => handleCancel(selectedTask.id)}
                      disabled={selectedTask.status !== 'running'}
                    >
                      取消
                    </ToolbarButton>
                  </div>
                </div>

                {selectedTask.status === 'failed' && selectedTask.errorMessage ? (
                  <div style={{ marginTop: 16, padding: '12px 14px', borderRadius: 'var(--radius-sm)', background: 'var(--error-soft)', border: '1px solid color-mix(in oklch, var(--error) 24%, transparent)' }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--error)' }}>
                      {typeof selectedTask.error?.code === 'string' ? selectedTask.error.code : 'TASK_FAILED'}
                      {' · '}{selectedTask.stage || '执行'}
                    </div>
                    <div style={{ marginTop: 6, fontSize: 13, color: 'var(--fg)', wordBreak: 'break-word' }}>
                      {selectedTask.errorMessage}
                    </div>
                    {selectedTask.detail && selectedTask.detail !== selectedTask.errorMessage ? (
                      <div style={{ marginTop: 6, fontSize: 12, color: 'var(--muted)', wordBreak: 'break-word' }}>
                        {selectedTask.detail}
                      </div>
                    ) : null}
                    {shouldSuggestProviderVerification(selectedTask) ? (
                      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 12, color: 'var(--muted)', flex: '1 1 280px' }}>
                          任务已经实际尝试执行。请主动验证服务连接或检查配置，然后再重试。
                        </span>
                        <ToolbarButton variant="secondary" onClick={() => setPage('settings')}>
                          去设置验证连接
                        </ToolbarButton>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                <div style={{ marginTop: 18, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 180px), 1fr))', gap: 12 }}>
                  {[
                    { label: '当前阶段', value: stageLabel(selectedTask) },
                    { label: '任务 ID', value: selectedTask.serverTaskId || selectedTask.id },
                    ...(selectedTask.retryOfTaskId
                      ? [{ label: '重试自任务', value: selectedTask.retryOfTaskId }]
                      : []),
                    { label: '耗时', value: formatDuration((selectedTask.finishedAt ?? Date.now()) - (selectedTask.startedAt ?? selectedTask.createdAt)) },
                    { label: '源文件', value: selectedTask.sourcePath },
                  ].map((item) => (
                    <div key={item.label} style={{ padding: '12px 14px', borderRadius: 'var(--radius-sm)', background: 'var(--panel-muted)' }}>
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{item.label}</div>
                      <div style={{ marginTop: 6, fontSize: 13, fontWeight: 600, color: 'var(--fg)', wordBreak: 'break-all' }}>{item.value}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="task-center-detail-pair">
                <div style={{ ...SURFACE_STYLE, padding: '18px 20px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 700 }}>执行进度</div>
                      <div className="task-center-break-anywhere" style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>{selectedTask.message || '等待状态回传'}</div>
                    </div>
                    <div style={{ fontSize: 28, fontWeight: 700, fontFamily: 'var(--font-display)' }}>
                      {Math.max(0, Math.min(100, selectedTask.progress))}%
                    </div>
                  </div>

                  <div style={{ marginTop: 16, height: 8, borderRadius: 999, background: 'var(--panel-muted)', overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${Math.max(0, Math.min(100, selectedTask.progress))}%`,
                        height: '100%',
                        background: selectedTask.status === 'failed' ? 'var(--error)' : selectedTask.status === 'completed' ? 'var(--success)' : 'var(--accent)',
                      }}
                    />
                  </div>

                  {selectedTask.jobType === 'pipeline' ? (
                    <div style={{ marginTop: 18 }}>
                      <PipelineTimeline task={selectedTask} />
                    </div>
                  ) : (
                    <div style={{ marginTop: 18, padding: '12px 14px', borderRadius: 'var(--radius-sm)', background: 'var(--panel-muted)' }}>
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>后端阶段</div>
                      <div style={{ marginTop: 6, fontSize: 13, fontWeight: 600 }}>
                        {selectedTask.stage || (selectedTask.status === 'pending' ? '等待执行' : '执行')}
                      </div>
                    </div>
                  )}
                </div>

                <div style={{ ...SURFACE_STYLE, padding: '18px 20px' }}>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>产物入口</div>
                  <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>
                    完成后优先看主产物，其余文件作为排障或复核材料。
                  </div>

                  {artifacts.length === 0 ? (
                    <div style={{ marginTop: 18, fontSize: 13, color: 'var(--muted)' }}>后端还没有返回产物文件。</div>
                  ) : (
                    <div style={{ marginTop: 18, display: 'grid', gap: 12 }}>
                      {artifacts.map((artifact) => (
                        <div key={artifact.artifactId} style={{ padding: '12px 14px', borderRadius: 'var(--radius-sm)', background: 'var(--panel-muted)' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                            <div style={{ minWidth: 0, flex: '1 1 240px' }}>
                              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg)' }}>
                                {artifact.primary ? '主产物' : artifact.label || artifact.type}
                              </div>
                              <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)', wordBreak: 'break-all' }}>
                                {artifact.path}
                              </div>
                            </div>

                            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                              {artifact.preview && artifact.type.startsWith('audio.') ? (
                                <ToolbarButton variant="secondary" onClick={() => handlePlayArtifact(artifact.artifactId, artifact.label || artifact.type)}>
                                  播放
                                </ToolbarButton>
                              ) : null}
                              <ToolbarButton variant="ghost" onClick={() => void copyToClipboard(artifact.path)}>
                                复制路径
                              </ToolbarButton>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="task-center-detail-pair">
                <div style={{ ...SURFACE_STYLE, padding: '18px 20px' }}>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>参数快照</div>
                  <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>
                    失败排查先看这里，而不是先翻日志。
                  </div>

                  <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 180px), 1fr))', gap: 12 }}>
                    {Object.entries(selectedTask.params).map(([key, value]) => (
                      <div key={key} style={{ padding: '12px 14px', borderRadius: 'var(--radius-sm)', background: 'var(--panel-muted)' }}>
                        <div style={{ fontSize: 11, color: 'var(--muted)' }}>{paramLabel(key)}</div>
                        <div style={{ marginTop: 6, fontSize: 12, color: 'var(--fg)', wordBreak: 'break-all' }}>
                          {formatParamValue(value)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div style={{ ...SURFACE_STYLE, padding: '18px 20px', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 700 }}>日志</div>
                      <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>
                        日志只作为详情区的排障工具。
                      </div>
                    </div>
                    <ToolbarButton variant="ghost" onClick={clearLogs} disabled={logs.length === 0}>
                      清空日志
                    </ToolbarButton>
                  </div>

                  <div style={{ marginTop: 14, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {LOG_LEVELS.map((level) => (
                      <button
                        key={level.value}
                        type="button"
                        onClick={() => toggleLogLevel(level.value)}
                        style={{
                          padding: '6px 10px',
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid var(--border)',
                          background: levelFilter.includes(level.value) ? 'var(--accent-soft)' : 'var(--surface)',
                          color: levelFilter.includes(level.value) ? 'var(--accent)' : 'var(--muted-strong)',
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        {level.label}
                      </button>
                    ))}
                  </div>

                  <div
                    style={{
                      marginTop: 14,
                      flex: 1,
                      minHeight: 220,
                      overflow: 'auto',
                      display: 'grid',
                      gap: 10,
                    }}
                  >
                    {filteredLogs.length === 0 ? (
                      <div style={{ display: 'grid', placeItems: 'center', minHeight: 180, color: 'var(--muted)' }}>
                        当前任务暂无匹配日志。
                      </div>
                    ) : (
                      filteredLogs.map((entry) => (
                        <div
                          key={entry.id}
                          style={{
                            padding: '12px 14px',
                            borderRadius: 'var(--radius-sm)',
                            background: 'var(--panel-muted)',
                            borderLeft: `3px solid ${
                              entry.level === 'error'
                                ? 'var(--error)'
                                : entry.level === 'warn'
                                  ? 'var(--warning)'
                                  : 'var(--accent)'
                            }`,
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 11, color: 'var(--muted)' }}>
                            <span>{entry.level.toUpperCase()}</span>
                            <span>{formatDateTime(entry.timestamp)}</span>
                          </div>
                          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--fg)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                            {entry.content}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
