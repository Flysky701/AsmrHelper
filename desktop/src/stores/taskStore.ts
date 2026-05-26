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
  | 'voice-design'
  | 'voice-clone'
  | 'voice-preview'

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'skipped'

export interface Task {
  id: string
  serverTaskId?: string
  jobType: JobType
  sourceName: string
  sourcePath: string
  status: TaskStatus
  progress: number
  message: string
  detail: string
  createdAt: number
  startedAt?: number
  finishedAt?: number
  artifacts?: { files: Record<string, string>; primaryOutput?: string }
  errorMessage?: string
  params: Record<string, unknown>
}

type FilterType = 'all' | 'running' | 'pending' | 'completed' | 'failed' | 'cancelled' | 'skipped'

interface TaskStore {
  tasks: Task[]
  filter: FilterType
  selectedTaskId: string | null

  addTask: (task: Omit<Task, 'id' | 'status' | 'progress' | 'createdAt' | 'message' | 'detail'>) => string
  updateTask: (id: string, patch: Partial<Task>) => void
  removeTask: (id: string) => void
  setFilter: (filter: FilterType) => void
  selectTask: (id: string | null) => void
  startAll: () => void
  pauseAll: () => void
  syncFromServer: (serverTasks: Array<{ task_id: string; state: string; progress: number; message: string; detail: string }>) => void
}

let nextId = 1

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

  removeTask: (id) =>
    set((s) => ({
      tasks: s.tasks.filter((t) => t.id !== id),
      selectedTaskId: s.selectedTaskId === id ? null : s.selectedTaskId,
    })),

  setFilter: (filter) => set({ filter }),

  selectTask: (id) => set({ selectedTaskId: id }),

  startAll: () =>
    set((s) => ({
      tasks: s.tasks.map((t) =>
        t.status === 'pending' ? { ...t, status: 'running' as const } : t
      ),
    })),

  pauseAll: () =>
    set((s) => ({
      tasks: s.tasks.map((t) =>
        t.status === 'running' ? { ...t, status: 'pending' as const } : t
      ),
    })),

  syncFromServer: (serverTasks) =>
    set((s) => ({
      tasks: s.tasks.map((local) => {
        const remote = serverTasks.find(
          (st) => st.task_id === (local.serverTaskId ?? local.id)
        )
        if (!remote) return local
        return {
          ...local,
          serverTaskId: remote.task_id,
          status: remote.state as TaskStatus,
          progress: remote.progress,
          message: remote.message,
          detail: remote.detail,
        }
      }),
    })),
}))
