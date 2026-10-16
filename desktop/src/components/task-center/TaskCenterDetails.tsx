import { t, format as formatMessage, useI18n } from '@/i18n'
import { displayPath } from '@/utils/displayPath'
import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Task, TaskStatus } from '@/stores/taskStore'
import type { LogEntry, LogLevel } from '@/stores/logStore'
import type { TaskExecutionView } from '@/domain/taskExecutionView'
import { artifactGroup, artifactNodeId, frozenTaskGraph, frozenTaskInputs } from '@/domain/taskCenterPresentation'

const labels: Record<string, string> = {
  running: '运行中', pending: '待处理', completed: '已完成', failed: '失败',
  cancelled: '已取消', skipped: '已跳过', unknown: '未知',
}
export function TaskStatusLabel({ state }: { state: TaskStatus | string }) {
  useI18n()
  return <span className={`tc-status ${state}`}><i />{t(labels[state] || state)}</span>
}
export function TaskSymbol({ name }: { name: string }) {
  return <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
    {name === 'search' ? <><circle cx="8.5" cy="8.5" r="5" /><path d="m12 12 5 5" /></>
      : name === 'folder' ? <path d="M2 5h6l2 2h8v10H2z" />
      : name === 'file' ? <><path d="M5 2h7l4 4v12H5zM12 2v5h4M8 11h5M8 14h5" /></>
      : name === 'refresh' ? <path d="M16 7a6 6 0 1 0 0 7M16 3v4h-4" />
      : <path d="m7 4 6 6-6 6" />}
  </svg>
}
const dateTime = (value?: number) => value ? new Date(value).toLocaleString() : t("尚未开始")
const clock = (value: number) => new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const formatValue = (value: unknown) => value === null || value === undefined || value === '' ? '—'
  : typeof value === 'boolean' ? value ? t("开启") : t("关闭")
  : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
const paramLabels: Record<string, string> = {
  input_path: '输入文件', source_lang: '源语言', target_lang: '目标语言', use_vocal_separator: '人声分离',
  tts_engine: 'TTS 引擎', tts_voice: 'TTS 声线', vocal_model: '分离模型', asr_model: 'ASR 模型',
  translate_provider: '翻译提供方', tts_speed: '语速', original_volume: '原声保留', tts_volume_ratio: 'TTS 音量占比',
  tts_delay: 'TTS 延迟', skip_existing: '跳过已有输出', voice_profile_id: '音色档案', graph: '流程快照', bindings: '输入绑定',
}
type Tab = 'nodes' | 'artifacts' | 'errors' | 'events' | 'params'
const groupLabels = { final: '最终交付', intermediate: '中间片段', unconfirmed: '交付归属未确认' }

function AudioProcessingDetails({ metadata }: { metadata?: Record<string, unknown> }) {
  if (!metadata) return null
  const number = (key: string) => typeof metadata[key] === 'number' && Number.isFinite(metadata[key]) ? metadata[key] as number : undefined
  const offset = number('offset_ms'), attenuation = number('safety_gain')
  const start = number('coverage_start'), end = number('coverage_end')
  const gains = Array.isArray(metadata.gains) ? metadata.gains.filter((value): value is number => typeof value === 'number' && Number.isFinite(value)) : []
  const warnings = Array.isArray(metadata.warnings) ? metadata.warnings.filter((value): value is string => typeof value === 'string') : []
  return <>
    {offset !== undefined && <p>{formatMessage("基准偏移：{0} ms", [offset.toFixed(3)])}{gains.length > 0 && formatMessage(" · 实际增益：{0}", [gains.map(value => value.toFixed(4)).join(" / ")])}</p>}
    {start !== undefined && end !== undefined && <p>{formatMessage("有效差分区间：{0}–{1} 秒；区间外保留含效果音原音频。", [start.toFixed(3), end.toFixed(3)])}</p>}
    {attenuation !== undefined && attenuation < 1 && <p>{formatMessage("混音峰值保护：整轨输出乘以 {0}，保留各轨相对音量。", [attenuation.toFixed(4)])}</p>}
    {warnings.map((warning, index) => <p className="tc-evidence-note" key={index}>{t(warning)}</p>)}
  </>
}

export default function TaskCenterDetails({ task, execution, events, batchName, visible, stage, jobLabel,
  actions, recovery, onBack, onPlay, onCopy, onConfigure, levelFilter, onToggleLevel, onClearLogs,
}: {
  task: Task
  execution?: TaskExecutionView
  events: LogEntry[]
  batchName?: string
  visible: boolean
  stage: string
  jobLabel: string
  actions: ReactNode
  recovery: ReactNode
  onBack: () => void
  onPlay: (artifactId: string, title: string) => void
  onCopy: (path: string) => void
  onConfigure: () => void
  levelFilter: LogLevel[]
  onToggleLevel: (level: LogLevel) => void
  onClearLogs: () => void
}) {
  useI18n()
  const [tab, setTab] = useState<Tab>('nodes')
  const [nodeId, setNodeId] = useState<string | null>(null)
  const [previewId, setPreviewId] = useState<string | null>(null)
  const taskId = task.serverTaskId || task.id
  const graph = frozenTaskGraph(task, execution)
  const artifacts = task.artifacts?.items ?? []
  const shownArtifacts = artifacts.filter(artifact => !nodeId || artifactNodeId(artifact) === nodeId)
  const nodeEvents = events.filter(event => !nodeId || event.stage === nodeId)
  const shownEvents = nodeEvents.filter(event => levelFilter.includes(event.level)).slice(0, 120)
  const errorMessage = task.errorMessage || (typeof task.error?.message === 'string' ? task.error.message : '')
  const errorNodeId = typeof task.error?.node_id === 'string' ? task.error.node_id : undefined
  const errorCode = typeof task.error?.code === 'string' ? task.error.code : 'TASK_FAILED'
  const hasError = Boolean(errorMessage || task.error)
  const selectedStep = execution?.steps.find(step => step.id === nodeId)
  const groups = (['final', 'intermediate', 'unconfirmed'] as const).map(id => ({ id,
    items: shownArtifacts.filter(artifact => artifactGroup(artifact, graph) === id),
    total: artifacts.filter(artifact => artifactGroup(artifact, graph) === id).length,
  }))
  const tabs: Array<{ id: Tab; label: string; count?: number }> = [
    { id: 'nodes', label: task.jobType === 'pipeline' ? t("流程节点") : t("执行进度"), count: execution?.total ?? undefined },
    { id: 'artifacts', label: t("产物"), count: artifacts.length }, { id: 'errors', label: t("错误"), count: hasError ? 1 : 0 },
    { id: 'events', label: t("事件"), count: events.length }, { id: 'params', label: t("参数") },
  ]
  return <>
    <header className="tc-detail-header">
      <button type="button" className="tc-back" onClick={onBack}>{t("‹ 返回任务列表")}</button>
      <div className="tc-breadcrumb">{batchName || t("独立任务")}<span> / {jobLabel}</span></div>
      <div className="tc-detail-title"><h2>{task.sourceName}</h2><TaskStatusLabel state={task.status} /></div>
      <div className="tc-task-meta"><code>{taskId}</code><span>{t("开始于")}{dateTime(task.startedAt)}</span></div>
      {task.retryOfTaskId && <div className="tc-task-meta"><span>{t("来源任务")}<code>{task.retryOfTaskId}</code></span></div>}
      {!visible && <p className="tc-selection-note">{t("当前筛选未包含此任务，仍保留正在查看的详情。")}</p>}
      <div className="tc-task-actions">{actions}</div>
    </header>
    <nav className="tc-detail-tabs" aria-label={t("任务详情分类")}>{tabs.map(item => <button key={item.id} type="button"
      aria-pressed={tab === item.id} onClick={() => { setTab(item.id); setNodeId(null); setPreviewId(null) }}>
      {item.label}{item.count !== undefined && <small>{item.count}</small>}</button>)}</nav>
    <div className="tc-detail-scroll">
      {tab === 'nodes' && <>
        <div className="tc-node-summary"><div><strong>{execution ? t("本次运行的节点") : t(stage)}</strong>{!execution && <span>{t(task.message || '') || t("等待状态回传")}</span>}</div>
          {execution ? <b data-testid="completed-nodes">{t(execution.summary)}</b> : <b>{Math.max(0, Math.min(100, task.progress))}%</b>}</div>
        {execution && <p className="tc-current-stage">{t("当前阶段：")}{t(stage)}</p>}
        {!execution && <div className="tc-progress" role="progressbar" aria-label={t("执行进度")} aria-valuenow={Math.max(0, Math.min(100, task.progress))} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${Math.max(0, Math.min(100, task.progress))}%` }} /></div>}
        {execution && !execution.steps.length && <div className="tc-empty"><span className="tc-empty-glyph">◇</span><strong>{t("这条记录没有可用的节点快照")}</strong><p>{t("可查看任务状态、已有产物和事件。")}</p></div>}
        {execution?.steps.some(step => step.state === 'unknown') && <p className="tc-evidence-note">{t("部分节点缺少完成证据，状态保留为未知；已有片段不代表节点完成。")}</p>}
        {!!execution?.steps.length && <div className="tc-nodes">{execution.steps.map((step, index) => {
          const node = graph?.nodes.find(item => item.id === step.id)
          const name = t(step.label.endsWith(` · ${step.id}`) ? step.label.slice(0, -(` · ${step.id}`).length) : step.label)
          return <div className="tc-node-wrap" key={step.id}>
            <button type="button" className={`tc-node-row ${step.state} ${nodeId === step.id ? 'selected' : ''}`}
              data-node-id={step.id} aria-expanded={nodeId === step.id} aria-label={formatMessage("查看节点 {0} {1}", [name, step.id])}
              onClick={() => setNodeId(nodeId === step.id ? null : step.id)}>
              <span className="tc-node-mark">{step.state === 'completed' ? '✓' : step.state === 'failed' ? '!' : step.state === 'running' ? <span /> : String(index + 1).padStart(2, '0')}</span>
              <span className="tc-node-name"><strong>{name}</strong><code>{step.id}</code><small>{typeof node?.provider === 'string' ? node.provider : ''}{typeof node?.model === 'string' ? ` · ${node.model}` : ''}</small></span>
              <TaskStatusLabel state={step.state} /><span className={`tc-chevron ${nodeId === step.id ? 'open' : ''}`}><TaskSymbol name="chevron" /></span>
            </button>
            {nodeId === step.id && <div className="tc-node-evidence"><div><span>{t("任务")}</span><code>{taskId}</code></div><div><span>{t("节点")}</span><code>{step.id}</code></div>
              <p className={errorNodeId === step.id ? 'tc-error-text' : ''}>{errorNodeId === step.id ? errorMessage
                : step.state === 'completed' ? t("此节点已有明确完成证据。")
                : step.state === 'running' ? t("后端报告正在执行此节点；暂无节点内进度。")
                : step.state === 'unknown' ? t("没有足够的节点事件，不能确认此节点的状态。") : formatMessage("节点状态：{0}", [t(labels[step.state] || step.state)])}</p>
              <div className="tc-inline-actions"><button type="button" onClick={() => setTab('events')}>{t("查看此节点事件")}<b>{nodeEvents.length}</b></button><button type="button" onClick={() => setTab('artifacts')}>{t("查看此节点产物")}<b>{shownArtifacts.length}</b></button></div>
            </div>}
          </div>
        })}</div>}
        <div className="tc-frozen-inputs"><span>{t("本次输入")}</span>{frozenTaskInputs(task).map(input => <p key={input.label}>{!task.params.bindings && input.label === '输入文件' ? t('输入文件') : input.label} · {displayPath(input.path)}</p>)}</div>
        {!!graph?.outputs.length && <div className="tc-final-output"><span>{t("计划交付")}</span>{graph.outputs.map(output => <code key={`${output.node_id}.${output.port}`}>{output.node_id}.{output.port}</code>)}</div>}
        {task.message && execution && <p className="tc-message">{t(task.message)}</p>}
        {recovery}
      </>}
      {tab !== 'nodes' && <div className="tc-scope"><span>{nodeId ? selectedStep ? `${t(selectedStep.label.replace(` · ${selectedStep.id}`, ''))} · ${selectedStep.id}` : nodeId : t('全部节点')}</span><code>{taskId}</code>{nodeId && <button type="button" onClick={() => setNodeId(null)}>{t("清除节点筛选")}</button>}</div>}
      {tab === 'artifacts' && <>
        <p className="tc-artifact-notice">{groups.map(group => `${t(groupLabels[group.id])} ${group.total}`).join(' · ')}<span>{t("中间片段不代表流程完成；缺少节点标记时，只归属到当前任务。")}</span></p>
        {(task.artifacts?.warnings ?? []).map((warning, index) => <p className="tc-evidence-note" key={index}>{t(warning)}</p>)}
        {!shownArtifacts.length && <div className="tc-empty"><span className="tc-empty-glyph">▱</span><strong>{nodeId ? t("此节点暂无产物") : t("此任务暂无产物")}</strong></div>}
        {groups.filter(group => group.items.length).map(group => <section key={group.id} className="tc-artifacts" aria-label={t(groupLabels[group.id])}><h3>{t(groupLabels[group.id])} <small>{group.items.length}</small></h3>{group.items.map(artifact => <article key={artifact.artifactId} data-artifact-task={taskId}>
          <div className="tc-artifact-icon">{artifact.type.startsWith('audio.') ? '♫' : '≡'}</div>
          <div><strong>{artifact.label || artifact.type}</strong><p><code>{artifactNodeId(artifact) || t("节点未记录")}</code><span>{artifact.type}</span></p><small>{taskId}</small><AudioProcessingDetails metadata={artifact.metadata} /></div>
          {artifact.preview && artifact.type.startsWith('audio.') && <button type="button" onClick={() => onPlay(artifact.artifactId, artifact.label || artifact.type)}>{t("播放")}</button>}
          <button type="button" onClick={() => setPreviewId(previewId === artifact.artifactId ? null : artifact.artifactId)} aria-expanded={previewId === artifact.artifactId}>{t("文件详情")}</button>
          {previewId === artifact.artifactId && <div className="tc-artifact-preview"><strong>{artifact.label || artifact.type}</strong><p>{displayPath(artifact.path)}</p><p>{t("归属：")}{taskId} / {artifactNodeId(artifact) || t("节点未记录")}</p><button type="button" onClick={() => onCopy(artifact.path)}>{t("复制路径")}</button></div>}
        </article>)}</section>)}
      </>}
      {tab === 'errors' && (hasError ? <>
        <div className="tc-error-card" role="alert" aria-label={t("任务错误")}><span className="tc-error-code">{errorCode}</span><h3>{errorNodeId ? formatMessage("节点 {0} 执行失败", [errorNodeId]) : t("任务执行失败")}</h3><p>{errorMessage || t("后端未提供错误描述")}</p>
          {task.detail && task.detail !== errorMessage && <p>{task.detail}</p>}
          <footer><code>{taskId}</code><span>{errorNodeId || t("节点未记录")}</span></footer><p>{task.finishedAt ? formatMessage("失败于 {0}", [dateTime(task.finishedAt)]) : t("失败时间未记录")}</p>
          <button type="button" onClick={() => { setNodeId(errorNodeId || null); setTab('events') }}>{t("查看关联事件")}</button>
          {task.status === 'failed' && (task.error?.action === 'settings' || errorCode === 'PROVIDER_EXECUTION_FAILED') && <div className="tc-error-help"><p>{t("任务已经实际尝试执行。请验证服务连接或检查配置，然后再重试。")}</p><button type="button" onClick={onConfigure}>{t("配置外部服务")}</button></div>}
        </div>{recovery}</> : <div className="tc-empty"><span className="tc-empty-glyph">○</span><strong>{t("没有错误记录")}</strong></div>)}
      {tab === 'events' && <>
        <div className="tc-log-controls">{(['info', 'warn', 'error'] as const).map((level, index) => <button type="button" key={level} aria-pressed={levelFilter.includes(level)} onClick={() => onToggleLevel(level)}>{[t("信息"), t("警告"), t("错误")][index]}</button>)}<button type="button" onClick={onClearLogs} disabled={!events.length}>{t("清空全部日志")}</button></div>
        {shownEvents.length ? <ol className="tc-events">{shownEvents.map(event => <li key={event.id} data-event-task={event.serverTaskId || taskId}><time title={dateTime(event.timestamp)}>{clock(event.timestamp)}</time><span className={`tc-event-dot ${event.level}`} /><div><strong>{t(event.content)}</strong><p><code>{event.stage || t("任务")}</code><span>{event.eventType || t("界面消息")}</span></p>{event.detail && <p className="tc-event-detail">{event.detail}</p>}<small>{event.serverTaskId || taskId}{event.sequence !== undefined ? ` · #${event.sequence}` : ''}</small></div></li>)}</ol>
          : <div className="tc-empty"><strong>{t("暂无可显示的事件")}</strong><p>{t("事件可能尚未产生、已清空，或不在当前筛选范围内。")}</p></div>}
      </>}
      {tab === 'params' && <div className="tc-params"><p>{t("本次提交的参数快照")}</p><dl>{Object.entries(task.params).map(([key, value]) => <div key={key}><dt>{t(paramLabels[key] || key)}</dt><dd><pre>{formatValue(value)}</pre></dd></div>)}</dl>{!Object.keys(task.params).length && <div className="tc-empty">{t("没有已记录的参数。")}</div>}</div>}
    </div>
    <footer className="tc-detail-footer"><span>{t("创建于")}{dateTime(task.createdAt)}</span></footer>
  </>
}
