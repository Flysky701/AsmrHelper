import type { LogEntry } from '@/stores/logStore'
import type { Task } from '@/stores/taskStore'

const labels: Record<string, string> = {
  prepare: '准备', separate: '人声分离', asr: 'ASR 识别', align: '字幕对齐',
  translate: '字幕翻译', tts: 'TTS 合成', mix: '混音输出', export: '导出产物', audio_export: '音频导出',
}
const kinds = ['separate', 'asr', 'align', 'translate', 'tts', 'mix', 'export']
const graphKinds = [...kinds, 'audio_export']
type StepState = 'completed' | 'running' | 'failed' | 'cancelled' | 'pending' | 'unknown'
export interface TaskExecutionStep { id: string; label: string; state: StepState }
export interface TaskExecutionView {
  source: 'graph' | 'legacy' | 'unknown'
  steps: TaskExecutionStep[]
  currentLabel: string
  summary: string
  completed: number | null
  total: number | null
}
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

/** The same stable dependency order as GraphExecutor; malformed specs stay unknown. */
function graphSteps(profile: Record<string, unknown>): TaskExecutionStep[] | null {
  const graph = profile.graph
  if (!record(graph) || graph.version !== 2 || !Array.isArray(graph.nodes) || !graph.nodes.length
    || !Array.isArray(graph.edges)) return null
  const steps: TaskExecutionStep[] = []
  for (const node of graph.nodes) {
    if (!record(node) || typeof node.id !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(node.id)
      || typeof node.kind !== 'string' || !graphKinds.includes(node.kind)) return null
    const id = node.id
    if (steps.some(step => step.id.toLowerCase() === id.toLowerCase())) return null
    steps.push({ id, label: `${labels[node.kind]} · ${id}`, state: 'unknown' })
  }
  const dependencies = new Map(steps.map(step => [step.id, new Set<string>()]))
  for (const edge of graph.edges) {
    if (!record(edge) || !record(edge.source) || !record(edge.target)
      || typeof edge.target.node_id !== 'string' || !dependencies.has(edge.target.node_id)) return null
    if (edge.source.kind === 'node') {
      if (typeof edge.source.node_id !== 'string' || !dependencies.has(edge.source.node_id)) return null
      dependencies.get(edge.target.node_id)!.add(edge.source.node_id)
    } else if (edge.source.kind !== 'slot' || typeof edge.source.slot_id !== 'string') return null
  }
  const ordered: TaskExecutionStep[] = [], seen = new Set<string>()
  while (ordered.length < steps.length) {
    const next = steps.find(step => !seen.has(step.id) && [...dependencies.get(step.id)!].every(id => seen.has(id)))
    if (!next) return null
    ordered.push(next); seen.add(next.id)
  }
  return ordered
}

function taskEvents(task: Task, logs: LogEntry[]): LogEntry[] {
  if (!task.serverTaskId) return []
  const events = logs.filter(entry => entry.serverTaskId === task.serverTaskId
    && Number.isInteger(entry.sequence) && entry.sequence! > 0 && Number.isFinite(entry.timestamp)
    && entry.timestamp >= task.createdAt && (!task.finishedAt || entry.timestamp <= task.finishedAt))
    .sort((a, b) => a.sequence! - b.sequence!)
  // A sequence is scoped to one server task. Conflicting duplicates are not evidence.
  const counts = new Map<number, number>()
  events.forEach(event => counts.set(event.sequence!, (counts.get(event.sequence!) ?? 0) + 1))
  const unique = events.filter(event => counts.get(event.sequence!) === 1)
  const resets = unique.filter(event => event.eventType === 'task_started' || event.eventType === 'task_retried')
  const reset = resets[resets.length - 1]?.sequence ?? 0
  return unique.filter(event => event.sequence! >= reset)
}

/** Graph-only evidence: current GraphExecutor reports i/N at start and (i+1)/N
 * after validating outputs. The registry translates that same-node transition to
 * stage_progress. Require both observations; never use rounded Task.progress,
 * log prose, artifacts, another node's start, or this rule for the legacy engine.
 * Revisit this contract if graph callbacks gain internal node progress events.
 */
function confirmedGraphNodes(steps: TaskExecutionStep[], events: LogEntry[]): Set<string> {
  const completed = new Set<string>(), starts = new Set<string>()
  const count = steps.length
  for (const event of events) {
    const index = steps.findIndex(step => step.id === event.stage)
    const progress = event.data?.progress
    if (index < 0 || event.data?.state !== 'running' || typeof progress !== 'number' || !Number.isFinite(progress)) continue
    const id = steps[index]!.id
    if (['stage_started', 'task_started', 'task_updated'].includes(event.eventType ?? '') && Math.abs(progress - index / count) < 1e-9) {
      starts.add(id)
    } else if (event.eventType === 'stage_progress') {
      if (starts.has(id) && Math.abs(progress - (index + 1) / count) < 1e-9) completed.add(id)
      starts.delete(id)
    }
  }
  return completed
}

export function taskExecutionView(task: Task, logs: LogEntry[] = []): TaskExecutionView {
  let source: TaskExecutionView['source'] = 'unknown'
  let steps: TaskExecutionStep[] = []
  let total: number | null = null
  if (task.params.version === 2) {
    const graph = graphSteps(task.params)
    if (graph) { source = 'graph'; steps = graph; total = graph.length }
  } else if (task.params.version === 1 && record(task.params.stages)) {
    // buildPipelineExecutionProfile persists explicit stages.<kind>.enabled.
    // Omitted legacy flags can have backend defaults; do not invent them here.
    const flags = task.params.stages
    steps = kinds.filter(kind => record(flags[kind]) && flags[kind].enabled === true)
      .map(id => ({ id, label: labels[id]!, state: 'unknown' }))
    if (steps.length) {
      source = 'legacy'
      if (kinds.filter(kind => kind !== 'align').every(kind => record(flags[kind]) && typeof flags[kind].enabled === 'boolean')) total = steps.length
    }
  }
  const events = source === 'graph' ? taskEvents(task, logs) : []
  const completed = source === 'graph' && !['pending', 'skipped'].includes(task.status)
    ? confirmedGraphNodes(steps, events) : new Set<string>()
  // Successful graph execution validates every actual node before completing.
  // Legacy stages may instead be reused/skipped; task success proves no per-stage state.
  if (source === 'graph' && task.status === 'completed') steps.forEach(step => completed.add(step.id))
  const errorNode = typeof task.error?.node_id === 'string' ? task.error.node_id : undefined
  const currentId = task.status === 'failed' && errorNode ? errorNode : task.stage
  for (const step of steps) {
    step.state = completed.has(step.id) ? 'completed'
      : step.id === currentId && ['running', 'failed', 'cancelled'].includes(task.status) ? task.status as StepState
        : task.status === 'pending' ? 'pending' : 'unknown'
  }
  const phase = steps.find(step => step.id === currentId)?.label || (currentId ? labels[currentId] || currentId : '')
  const currentLabel = task.error?.code === 'TASK_INTERRUPTED' ? '任务已中断'
    : task.status === 'completed' ? '任务已完成'
      : task.status === 'failed' ? phase ? `任务在“${phase}”阶段失败` : '失败阶段未知'
        : task.status === 'cancelled' ? '任务已取消'
          : task.status === 'skipped' ? '任务被跳过'
            : phase || (task.status === 'pending' ? '等待执行' : '当前节点未知')
  return { source, steps, currentLabel, completed: source === 'graph' ? completed.size : null, total,
    summary: source === 'graph' ? `已确认完成 ${completed.size}/${total} 个节点`
      : total !== null ? `节点完成情况未知（共 ${total} 个步骤）` : '节点完成情况未知' }
}
