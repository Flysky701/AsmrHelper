import { create } from 'zustand'

export type JobType =
  | 'pipeline'
  | 'asr'
  | 'tts'
  | 'separate'
  | 'convert'
  | 'split'
  | 'translate-subtitle'
  | 'script-to-vtt'
  | 'volume-preview'
  | 'model-install'
  | 'voice-design'
  | 'voice-clone'
  | 'voice-preview'
  | 'unknown'

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'skipped'

export interface TaskArtifact {
  artifactId: string
  type: string
  path: string
  stage: string
  label: string
  primary: boolean
  preview: boolean
  metadata: Record<string, unknown>
}

export interface Task {
  id: string
  serverTaskId?: string
  jobType: JobType
  sourceName: string
  sourcePath: string
  status: TaskStatus
  stage?: string
  progress: number
  message: string
  detail: string
  createdAt: number
  startedAt?: number
  finishedAt?: number
  artifacts?: {
    primaryArtifactId?: string
    items: TaskArtifact[]
    warnings: string[]
  }
  errorMessage?: string
  error?: Record<string, unknown>
  retryOfTaskId?: string
  specLoaded?: boolean
  historical?: boolean
  params: Record<string, unknown>
}

type FilterType = 'all' | 'running' | 'pending' | 'completed' | 'failed' | 'cancelled' | 'skipped'

interface TaskStore {
  tasks: Task[]
  filter: FilterType
  selectedTaskId: string | null

  addTask: (task: Omit<Task, 'id' | 'status' | 'progress' | 'createdAt' | 'message' | 'detail'>) => string
  updateTask: (id: string, patch: Partial<Task>) => void
  setFilter: (filter: FilterType) => void
  selectTask: (id: string | null) => void
  syncFromServer: (serverTasks: Array<{
    task_id: string
    task_type?: string
    state: string
    stage?: string | null
    progress: number
    message: string
    detail: string
    error?: Record<string, unknown> | null
    input_asset_id?: string
    created_at?: string
    started_at?: string | null
    finished_at?: string | null
    retry_of_task_id?: string | null
  }>) => void
}

let nextId = 1

function taskErrorMessage(error?: Record<string, unknown> | null) {
  if (!error) return undefined
  if (typeof error.message === 'string' && error.message) return error.message
  if (typeof error.detail === 'string' && error.detail) return error.detail
  return '任务执行失败'
}

function parseServerTime(value?: string | null) {
  if (!value) return undefined
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? undefined : parsed
}

function jobTypeFromServer(taskType?: string): JobType {
  const mapping: Record<string, JobType> = {
    pipeline: 'pipeline',
    'tool.separate': 'separate',
    'tool.convert': 'convert',
    'tool.split': 'split',
    'tool.translate_subtitle': 'translate-subtitle',
    'tool.volume_preview': 'volume-preview',
    'subtitle.script_to_vtt': 'script-to-vtt',
    model_install: 'model-install',
    'voice.design': 'voice-design',
    'voice.clone': 'voice-clone',
    'voice.preview': 'voice-preview',
  }
  return mapping[taskType || ''] ?? 'unknown'
}

export const useTaskStore = create<TaskStore>((set) => ({
  tasks: [],
  filter: 'all',
  selectedTaskId: null,

  addTask: (task) => {
    const id = `task-${nextId++}`
    set((s) => ({
      tasks: [
        ...s.tasks,
        {
          ...task,
          id,
          status: 'pending',
          progress: 0,
          message: '',
          detail: '',
          createdAt: Date.now(),
        },
      ],
      selectedTaskId: s.selectedTaskId ?? id,
    }))
    return id
  },

  updateTask: (id, patch) =>
    set((s) => ({
      tasks: s.tasks.map((t) => {
        if (t.id !== id) return t

        const nextStatus = patch.status ?? t.status
        const hasStartedAtPatch = Object.prototype.hasOwnProperty.call(patch, 'startedAt')
        const hasFinishedAtPatch = Object.prototype.hasOwnProperty.call(patch, 'finishedAt')
        const isTerminal =
          nextStatus === 'completed' ||
          nextStatus === 'failed' ||
          nextStatus === 'cancelled' ||
          nextStatus === 'skipped'

        return {
          ...t,
          ...patch,
          startedAt:
            hasStartedAtPatch
              ? patch.startedAt
              : nextStatus === 'running'
              ? t.startedAt ?? Date.now()
              : t.startedAt,
          finishedAt:
            hasFinishedAtPatch
              ? patch.finishedAt
              : isTerminal
              ? t.finishedAt ?? Date.now()
              : t.finishedAt,
        }
      }),
    })),

  setFilter: (filter) => set({ filter }),

  selectTask: (id) => set({ selectedTaskId: id }),

  syncFromServer: (serverTasks) =>
    set((s) => {
      const updatedTasks = s.tasks.map((local) => {
        const remote = serverTasks.find(
          (st) => st.task_id === (local.serverTaskId ?? local.id)
        )
        if (!remote) return local
        return {
          ...local,
          serverTaskId: remote.task_id,
          status: remote.state as TaskStatus,
          stage: remote.stage ?? undefined,
          progress: Math.round(remote.progress * 100),
          message: remote.message,
          detail: remote.detail,
          errorMessage: taskErrorMessage(remote.error),
          error: remote.error ?? undefined,
          retryOfTaskId: remote.retry_of_task_id ?? undefined,
          startedAt: parseServerTime(remote.started_at) ?? local.startedAt,
          finishedAt: parseServerTime(remote.finished_at) ?? local.finishedAt,
        }
      })
      const boundServerIds = new Set(
        updatedTasks.map((task) => task.serverTaskId).filter(Boolean),
      )
      const historicalTasks: Task[] = serverTasks
        .filter((remote) => !boundServerIds.has(remote.task_id))
        .map((remote) => ({
          id: `server-${remote.task_id}`,
          serverTaskId: remote.task_id,
          jobType: jobTypeFromServer(remote.task_type),
          sourceName: remote.input_asset_id || remote.task_id,
          sourcePath: '',
          status: remote.state as TaskStatus,
          stage: remote.stage ?? undefined,
          progress: Math.round(remote.progress * 100),
          message: remote.message,
          detail: remote.detail,
          createdAt: parseServerTime(remote.created_at) ?? Date.now(),
          startedAt: parseServerTime(remote.started_at),
          finishedAt: parseServerTime(remote.finished_at),
          errorMessage: taskErrorMessage(remote.error),
          error: remote.error ?? undefined,
          retryOfTaskId: remote.retry_of_task_id ?? undefined,
          historical:
            remote.state === 'completed' ||
            remote.state === 'failed' ||
            remote.state === 'cancelled' ||
            remote.state === 'skipped',
          params: {},
        }))
      return {
        tasks: [...updatedTasks, ...historicalTasks],
        selectedTaskId:
          s.selectedTaskId ?? historicalTasks[0]?.id ?? null,
      }
    }),
}))
