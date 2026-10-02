import type { BatchRunResponse } from '@/api/types'
import type { LogEntry } from '@/stores/logStore'
import type { Task, TaskArtifact, TaskStatus } from '@/stores/taskStore'
import type { TaskExecutionView } from './taskExecutionView'

export type TaskStatusGroup = 'all' | 'processing' | 'attention' | 'ended'

export const TASK_STATUS_GROUPS: ReadonlyArray<{ value: TaskStatusGroup; label: string }> = [
  { value: 'all', label: '全部' }, { value: 'processing', label: '处理中' },
  { value: 'attention', label: '需关注' }, { value: 'ended', label: '已结束' },
]
export const TASK_STATUS_OPTIONS: ReadonlyArray<{ value: TaskStatus; label: string }> = [
  { value: 'running', label: '运行中' }, { value: 'pending', label: '待处理' },
  { value: 'failed', label: '失败' }, { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' }, { value: 'skipped', label: '已跳过' },
]

export function taskMatchesStatusGroup(status: TaskStatus, group: TaskStatusGroup): boolean {
  if (group === 'all') return true
  if (group === 'processing') return status === 'running' || status === 'pending'
  if (group === 'attention') return status === 'failed'
  return status === 'completed' || status === 'cancelled' || status === 'skipped'
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

/** Only server-issued membership establishes a batch relationship, including retries. */
export function taskBatchMembership(tasks: Task[], batches: BatchRunResponse[]): Map<string, BatchRunResponse> {
  const result = new Map<string, BatchRunResponse>()
  for (const task of tasks) {
    if (!task.serverTaskId) continue
    const matches = batches.filter(batch => batch.items.some(item =>
      item.current_task_id === task.serverTaskId || item.task_ids.includes(task.serverTaskId!)))
    const match = matches.length === 1 ? matches[0] : undefined
    if (match) result.set(task.id, match)
  }
  return result
}

/** Runtime IDs must agree. Local UI messages are scoped by their local task ID. */
export function taskPresentationEvents(task: Task, logs: LogEntry[]): LogEntry[] {
  return logs.filter(entry => entry.taskId === task.id
    && (!entry.serverTaskId || entry.serverTaskId === task.serverTaskId)
    && Number.isFinite(entry.timestamp) && entry.timestamp >= task.createdAt - 1000)
    .slice().sort((a, b) => {
      if (a.sequence !== undefined && b.sequence !== undefined) return b.sequence - a.sequence
      return b.timestamp - a.timestamp || b.id.localeCompare(a.id)
    })
}

export function frozenTaskGraph(task: Task, execution: TaskExecutionView | undefined) {
  const graph = task.params.graph
  if (execution?.source !== 'graph' || !record(graph)) return null
  const nodes = (Array.isArray(graph.nodes) ? graph.nodes : []).filter(record)
  return {
    nodes,
    outputs: (Array.isArray(graph.outputs) ? graph.outputs : []).filter(record)
      .filter(output => typeof output.node_id === 'string' && typeof output.port === 'string'
        && nodes.some(node => node.id === output.node_id))
      .map(output => ({ node_id: String(output.node_id), port: String(output.port) })),
  }
}

export function artifactNodeId(artifact: TaskArtifact): string | null {
  return typeof artifact.metadata.node_id === 'string' ? artifact.metadata.node_id : null
}

export type ArtifactGroup = 'final' | 'intermediate' | 'unconfirmed'
export function artifactGroup(artifact: TaskArtifact, graph: ReturnType<typeof frozenTaskGraph>): ArtifactGroup {
  // A speech take is a fragment even when legacy primary fallback selects it.
  if (artifact.type === 'audio.speech_take') return 'intermediate'
  return graph?.outputs.some(output => output.node_id === artifactNodeId(artifact)
    && output.port === artifact.metadata.port) ? 'final' : 'unconfirmed'
}

export function frozenTaskInputs(task: Task): Array<{ label: string; path: string }> {
  const bindings = task.params.bindings
  const inputs = record(bindings) ? Object.entries(bindings).flatMap(([label, value]) =>
    record(value) && typeof value.path === 'string' ? [{ label, path: value.path }] : []) : []
  return inputs.length ? inputs : task.sourcePath ? [{ label: '输入文件', path: task.sourcePath }] : []
}
