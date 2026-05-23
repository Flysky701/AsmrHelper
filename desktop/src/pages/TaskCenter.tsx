import { useTaskStore } from '@/stores/taskStore'
import type { Task, TaskStatus } from '@/stores/taskStore'
import { useLogStore } from '@/stores/logStore'
import type { LogLevel } from '@/stores/logStore'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { tasksApi } from '@/api/tasks'

/* ── Status pill ──────────────────────────────────── */
const STATUS_CONFIG: Record<TaskStatus, { label: string; dot: string; bg: string; color: string }> = {
  running:   { label: '运行中', dot: '#3b82f6', bg: '#eff6ff', color: '#1d4ed8' },
  pending:   { label: '排队中', dot: '#9ca3af', bg: '#f9fafb', color: '#6b7280' },
  completed: { label: '已完成', dot: '#22c55e', bg: '#f0fdf4', color: '#15803d' },
  failed:    { label: '失败',   dot: '#ef4444', bg: '#fef2f2', color: '#b91c1c' },
  cancelled: { label: '已取消', dot: '#9ca3af', bg: '#f9fafb', color: '#6b7280' },
  skipped:   { label: '已跳过', dot: '#9ca3af', bg: '#f9fafb', color: '#6b7280' },
}

function StatusPill({ status }: { status: TaskStatus }) {
  const c = STATUS_CONFIG[status]
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 500,
      background: c.bg, color: c.color, flexShrink: 0,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: c.dot }} />
      {c.label}
    </span>
  )
}

/* ── Pipeline stages ──────────────────────────────── */
const PIPELINE_STAGES = ['人声分离', 'ASR 识别', '翻译', 'TTS 合成', '混音'] as const

function guessPipelineStage(task: Task): number {
  const msg = (task.message + ' ' + task.detail).toLowerCase()
  if (msg.includes('separ') || msg.includes('分离')) return 0
  if (msg.includes('asr') || msg.includes('识别') || msg.includes('transcrib')) return 1
  if (msg.includes('translat') || msg.includes('翻译')) return 2
  if (msg.includes('tts') || msg.includes('合成')) return 3
  if (msg.includes('mix') || msg.includes('混音')) return 4
  if (task.status === 'completed') return 5
  return Math.floor(task.progress / 20)
}

function PipelineProgress({ task }: { task: Task }) {
  const activeIdx = guessPipelineStage(task)
  const isFailed = task.status === 'failed'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, marginTop: 12, flexWrap: 'wrap' }}>
      {PIPELINE_STAGES.map((name, i) => {
        let dotColor = '#e5e7eb'
        let animate = false
        if (i < activeIdx || task.status === 'completed') dotColor = '#22c55e'
        else if (i === activeIdx && task.status === 'running') { dotColor = '#3b82f6'; animate = true }
        else if (i === activeIdx && isFailed) dotColor = '#ef4444'
        return (
          <span key={name} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 500 }}>
            {i > 0 && <span style={{ color: '#d1d5db', margin: '0 4px', fontSize: 11 }}>&rarr;</span>}
            <span style={{
              width: 8, height: 8, borderRadius: '50%', background: dotColor, flexShrink: 0,
              animation: animate ? 'pulse 1.5s infinite' : undefined,
            }} />
            <span style={{ color: i <= activeIdx || task.status === 'completed' ? '#374151' : '#9ca3af' }}>
              {name}
            </span>
          </span>
        )
      })}
      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
    </div>
  )
}

/* ── Filter tabs ──────────────────────────────────── */
type FilterVal = 'all' | 'running' | 'pending' | 'completed' | 'failed'

const FILTER_TABS: { value: FilterVal; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'pending', label: '排队' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
]

/* ── Log level toggles ────────────────────────────── */
const LOG_LEVEL_OPTS: { value: LogLevel; label: string }[] = [
  { value: 'info', label: 'INFO' },
  { value: 'warn', label: 'WARN' },
  { value: 'error', label: 'ERROR' },
]

/* ── Main component ───────────────────────────────── */
export default function TaskCenter() {
  useTaskPolling(3000)

  const tasks = useTaskStore(s => s.tasks)
  const filter = useTaskStore(s => s.filter)
  const setFilter = useTaskStore(s => s.setFilter)
  const selectedTaskId = useTaskStore(s => s.selectedTaskId)
  const selectTask = useTaskStore(s => s.selectTask)
  const removeTask = useTaskStore(s => s.removeTask)
  const updateTask = useTaskStore(s => s.updateTask)

  const logs = useLogStore(s => s.logs)
  const levelFilter = useLogStore(s => s.levelFilter)
  const setLevelFilter = useLogStore(s => s.setLevelFilter)
  const clearLogs = useLogStore(s => s.clearLogs)
  const addLog = useLogStore(s => s.addLog)

  const showAudio = useAudioPlayerStore(s => s.show)

  const filtered = filter === 'all' ? tasks : tasks.filter(t => t.status === filter)
  const selected = tasks.find(t => t.id === selectedTaskId)

  const countByStatus = (s: TaskStatus) => tasks.filter(t => t.status === s).length
  const runningCount = countByStatus('running')
  const pendingCount = countByStatus('pending')

  const taskLogs = selectedTaskId
    ? logs.filter(l => l.taskId === selectedTaskId)
    : logs
  const filteredLogs = taskLogs.filter(l => levelFilter.includes(l.level))

  const toggleLogLevel = (lv: LogLevel) => {
    setLevelFilter(levelFilter.includes(lv) ? levelFilter.filter(l => l !== lv) : [...levelFilter, lv])
  }

  const handleCancel = async (taskId: string) => {
    const task = tasks.find(t => t.id === taskId)
    if (!task?.serverTaskId) { addLog({ level: 'warn', content: `任务尚未绑定后端 ID: ${taskId}`, taskId }); return }
    try {
      const res = await tasksApi.cancel(task.serverTaskId)
      updateTask(taskId, { status: 'cancelled', progress: res.progress, message: res.message || 'cancelled', detail: res.detail })
      addLog({ level: 'info', content: `任务已取消: ${task.serverTaskId}`, taskId })
    } catch (err) { addLog({ level: 'error', content: `取消失败: ${err}`, taskId }) }
  }

  const handleRetry = async (taskId: string) => {
    const task = tasks.find(t => t.id === taskId)
    if (!task?.serverTaskId) { addLog({ level: 'warn', content: `任务尚未绑定后端 ID: ${taskId}`, taskId }); return }
    try {
      const res = await tasksApi.retry(task.serverTaskId)
      updateTask(taskId, { status: 'pending', progress: res.progress, message: res.message || 'queued for retry', detail: res.detail })
      addLog({ level: 'info', content: `任务已重试: ${task.serverTaskId}`, taskId })
    } catch (err) { addLog({ level: 'error', content: `重试失败: ${err}`, taskId }) }
  }

  const handlePlayArtifact = (path: string, type: string) => showAudio(path, type)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', background: 'var(--bg)' }}>

      {/* ── Action Bar ───────────────────────────── */}
      <div style={{
        background: 'var(--surface)', borderBottom: '1px solid var(--border)',
        padding: '12px 24px', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0,
      }}>
        <h1 style={{ fontSize: 15, fontWeight: 600, letterSpacing: '-0.02em', marginRight: 8, fontFamily: 'var(--font-display)' }}>
          任务中心
        </h1>
        {runningCount > 0 && (
          <span style={{
            fontSize: 12, fontWeight: 500, padding: '3px 10px', borderRadius: 12,
            background: '#eff6ff', color: '#1d4ed8', whiteSpace: 'nowrap',
          }}>{runningCount} 运行中</span>
        )}
        {pendingCount > 0 && (
          <span style={{
            fontSize: 12, fontWeight: 500, padding: '3px 10px', borderRadius: 12,
            background: '#f9fafb', color: '#6b7280', whiteSpace: 'nowrap',
          }}>{pendingCount} 排队</span>
        )}
        <div style={{ flex: 1 }} />
        <button style={btnSuccessStyle}>启动</button>
        <button style={btnWarnStyle}>暂停</button>
        <button style={btnStyle}>重试失败</button>
        <button style={btnStyle}>取消全部</button>
      </div>

      {/* ── Content: list + detail ────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', flex: 1, overflow: 'hidden' }}>

        {/* ── Task List (left) ────────────────────── */}
        <div style={{ borderRight: '1px solid var(--border)', overflowY: 'auto', background: 'var(--surface)', display: 'flex', flexDirection: 'column' }}>
          {/* Filter bar */}
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 2, background: 'var(--surface)', flexShrink: 0 }}>
            {FILTER_TABS.map(tab => {
              const count = tab.value === 'all' ? tasks.length : tasks.filter(t => t.status === tab.value).length
              return (
                <button
                  key={tab.value}
                  onClick={() => setFilter(tab.value)}
                  style={{
                    padding: '5px 10px', fontSize: 12, fontWeight: 500, borderRadius: 4,
                    cursor: 'pointer', border: 'none',
                    background: filter === tab.value ? 'var(--bg)' : 'transparent',
                    color: filter === tab.value ? 'var(--fg)' : 'var(--muted)',
                  }}
                >
                  {tab.label}<span style={{ marginLeft: 3, fontSize: 11, opacity: 0.7 }}>{count}</span>
                </button>
              )
            })}
          </div>

          {/* Task items */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filtered.length === 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--muted)', fontSize: 13, gap: 8 }}>
                <span style={{ opacity: 0.3, fontSize: 24 }}>&#9744;</span>
                暂无任务
              </div>
            ) : filtered.map(task => {
              const isSelected = selectedTaskId === task.id
              return (
                <div
                  key={task.id}
                  onClick={() => selectTask(task.id)}
                  style={{
                    padding: isSelected ? '12px 14px 12px 14px' : '12px 16px',
                    borderBottom: '1px solid var(--border)',
                    cursor: 'pointer',
                    background: isSelected ? '#f0f4ff' : 'transparent',
                    borderLeft: isSelected ? '2px solid var(--accent)' : '2px solid transparent',
                    transition: 'background 0.1s',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <StatusPill status={task.status} />
                    <span style={{ fontSize: 13, fontWeight: 500, flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {task.sourceName}
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--muted)', flexShrink: 0 }}>
                      {formatRelativeTime(task.createdAt)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--muted)' }}>
                    <span>{jobTypeLabel(task.jobType)}</span>
                    {task.status === 'running' && (
                      <>
                        <span style={{ opacity: 0.4 }}>&middot;</span>
                        <span>{task.progress}%</span>
                      </>
                    )}
                    {task.message && (
                      <>
                        <span style={{ opacity: 0.4 }}>&middot;</span>
                        <span>{task.message}</span>
                      </>
                    )}
                    {task.status === 'completed' && task.finishedAt && task.startedAt && (
                      <>
                        <span style={{ opacity: 0.4 }}>&middot;</span>
                        <span>耗时 {formatDuration(task.finishedAt - task.startedAt)}</span>
                      </>
                    )}
                    {task.status === 'failed' && task.errorMessage && (
                      <>
                        <span style={{ opacity: 0.4 }}>&middot;</span>
                        <span style={{ color: '#b91c1c' }}>{task.errorMessage}</span>
                      </>
                    )}
                  </div>
                  {task.status === 'running' && (
                    <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, marginTop: 8, overflow: 'hidden' }}>
                      <div style={{ height: '100%', background: 'var(--accent)', borderRadius: 2, transition: 'width 0.3s', width: `${task.progress}%` }} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Detail Panel (right) ────────────────── */}
        <div style={{ padding: 24, overflowY: 'auto' }}>
          {!selected ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--muted)', fontSize: 13, gap: 8 }}>
              <span style={{ opacity: 0.3, fontSize: 24 }}>&#9744;</span>
              选择一个任务查看详情
            </div>
          ) : (
            <>
              {/* Header */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.02em', fontFamily: 'var(--font-display)', marginBottom: 4 }}>
                  {selected.sourceName}
                </div>
                <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                  {selected.serverTaskId || selected.id} &middot; {jobTypeLabel(selected.jobType)} &middot; 创建于 {new Date(selected.createdAt).toLocaleTimeString()}
                </div>
              </div>

              {/* Progress */}
              <div style={{ marginBottom: 20 }}>
                <h3 style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                  执行进度
                </h3>
                <div style={{ background: 'var(--bg)', borderRadius: 8, padding: 16 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <span style={{ fontSize: 24, fontWeight: 600, fontFamily: 'var(--font-display)' }}>{selected.progress}%</span>
                    <span style={{ fontSize: 12, color: 'var(--muted)' }}>{selected.message || '—'}</span>
                  </div>
                  <div style={{ height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ height: '100%', background: 'var(--accent)', borderRadius: 3, transition: 'width 0.3s', width: `${selected.progress}%` }} />
                  </div>
                  <PipelineProgress task={selected} />
                </div>
              </div>

              {/* Task params */}
              <div style={{ marginBottom: 20 }}>
                <h3 style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                  任务参数
                </h3>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  {Object.entries(selected.params).map(([key, val]) => (
                    <div key={key}>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2 }}>{paramLabel(key)}</div>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{String(val ?? '—')}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
                {(selected.status === 'pending' || selected.status === 'running') && (
                  <button style={btnDangerStyle} disabled={!selected.serverTaskId} onClick={() => handleCancel(selected.id)}>
                    <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4l6 6M10 4l-6 6" /></svg>
                    取消任务
                  </button>
                )}
                {(selected.status === 'failed' || selected.status === 'cancelled') && (
                  <button style={btnPrimaryStyle} disabled={!selected.serverTaskId} onClick={() => handleRetry(selected.id)}>
                    重试
                  </button>
                )}
                <button style={btnStyle} onClick={() => removeTask(selected.id)}>
                  删除
                </button>
              </div>

              {/* Output artifacts */}
              {selected.status === 'completed' && selected.artifacts && Object.keys(selected.artifacts.files).length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <h3 style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                    输出产物
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {Object.entries(selected.artifacts.files).map(([type, path]) => (
                      <div key={type} style={{
                        display: 'flex', alignItems: 'center', gap: 10,
                        padding: '10px 12px', background: 'var(--bg)', borderRadius: 6, fontSize: 13,
                      }}>
                        <span style={{ color: 'var(--muted)', fontSize: 14 }}>
                          {type.includes('audio') || type.includes('mix') ? '♪' : '📄'}
                        </span>
                        <span style={{ flex: 1, fontWeight: 500 }}>{path.split(/[/\\]/).pop()}</span>
                        <span style={{ fontSize: 11, color: 'var(--muted)' }}>{type}</span>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {(type.includes('audio') || type.includes('mix')) && (
                            <button style={smallBtnStyle} onClick={() => handlePlayArtifact(path, type)}>播放</button>
                          )}
                          <button style={smallBtnStyle}>打开目录</button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Logs for selected task */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <h3 style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    任务日志
                  </h3>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {LOG_LEVEL_OPTS.map(opt => (
                      <button
                        key={opt.value}
                        onClick={() => toggleLogLevel(opt.value)}
                        style={{
                          fontSize: 11, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)',
                          background: levelFilter.includes(opt.value) ? 'var(--accent)' : 'transparent',
                          color: levelFilter.includes(opt.value) ? 'white' : 'var(--muted)',
                          cursor: 'pointer',
                        }}
                      >{opt.label}</button>
                    ))}
                    <button style={{ ...smallBtnStyle, border: 'none' }} onClick={clearLogs}>清空</button>
                  </div>
                </div>
                <div style={{ background: 'var(--bg)', borderRadius: 8, padding: '8px 0', maxHeight: 200, overflowY: 'auto' }}>
                  {filteredLogs.length === 0 ? (
                    <div style={{ textAlign: 'center', color: 'var(--muted)', fontSize: 12, padding: 16 }}>暂无日志</div>
                  ) : filteredLogs.map(entry => (
                    <div key={entry.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '4px 12px', fontSize: 12, lineHeight: 1.5 }}>
                      <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--muted)', flexShrink: 0, fontSize: 11 }}>
                        {new Date(entry.timestamp).toLocaleTimeString()}
                      </span>
                      <span style={{
                        fontSize: 10, padding: '1px 4px', borderRadius: 3, flexShrink: 0,
                        background: entry.level === 'error' ? '#fef2f2' : entry.level === 'warn' ? '#fffbeb' : '#eff6ff',
                        color: entry.level === 'error' ? '#b91c1c' : entry.level === 'warn' ? '#92400e' : '#1d4ed8',
                      }}>{entry.level.toUpperCase()}</span>
                      <span style={{ wordBreak: 'break-word' }}>{entry.content}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/* ── Helpers ──────────────────────────────────────── */
function formatRelativeTime(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return new Date(ts).toLocaleDateString()
}

function formatDuration(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rs = s % 60
  return `${m}m ${rs}s`
}

function jobTypeLabel(t: string): string {
  const map: Record<string, string> = {
    pipeline: 'ASMR 双语双轨',
    'translate-subtitle': '字幕翻译',
    'script-to-vtt': '台本转字幕',
    separate: '人声分离',
    asr: 'ASR 识别',
    tts: 'TTS 合成',
    convert: '格式转换',
    split: '音频分割',
    'voice-design': '音色设计',
    'voice-clone': '音色克隆',
    'voice-preview': '音色试听',
  }
  return map[t] ?? t
}

function paramLabel(key: string): string {
  const map: Record<string, string> = {
    source_lang: '源语言',
    target_lang: '目标语言',
    tts_engine: 'TTS 引擎',
    tts_voice: 'TTS 音色',
    asr_model: 'ASR 模型',
    translate_provider: '翻译服务',
    vocal_model: '人声分离',
    tts_speed: '语速',
    original_volume: '原声音量',
    tts_volume_ratio: '配音音量比',
    tts_delay: '配音延迟',
    skip_existing: '跳过已存在',
    output_dir: '输出目录',
    input_path: '输入路径',
    vtt_path: 'VTT 字幕',
    use_vocal_separator: '人声分离',
    voice_profile_id: '音色配置',
    preset: '预设',
  }
  return map[key] ?? key
}

/* ── Button styles ────────────────────────────────── */
const btnBase: React.CSSProperties = {
  fontFamily: 'var(--font-body)', fontSize: 13, fontWeight: 500,
  padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'var(--surface)', color: 'var(--fg)', cursor: 'pointer',
  display: 'inline-flex', alignItems: 'center', gap: 6,
}
const btnStyle: React.CSSProperties = { ...btnBase }
const btnPrimaryStyle: React.CSSProperties = { ...btnBase, background: 'var(--accent)', color: 'white', borderColor: 'var(--accent)' }
const btnDangerStyle: React.CSSProperties = { ...btnBase, borderColor: '#fca5a5', color: '#b91c1c' }
const btnSuccessStyle: React.CSSProperties = { ...btnBase, background: '#22c55e', color: 'white', borderColor: '#22c55e' }
const btnWarnStyle: React.CSSProperties = { ...btnBase, background: '#fef3c7', color: '#92400e', borderColor: '#fde68a' }
const smallBtnStyle: React.CSSProperties = { fontSize: 11, padding: '3px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--muted)', cursor: 'pointer' }
