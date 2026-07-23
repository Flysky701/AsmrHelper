import { api } from './client'
import type {
  RuntimeEventResponse,
  TaskArtifactsResponse,
  TaskListResponse,
  TaskResultResponse,
  TaskStatusResponse,
} from './types'

const DEFAULT_API_BASE = 'http://127.0.0.1:8000/api/v1'
const API_BASE = import.meta.env.VITE_API_BASE?.trim() || DEFAULT_API_BASE

export const tasksApi = {
  list: () => api.get<TaskListResponse>('/tasks'),

  get: (taskId: string) =>
    api.get<TaskStatusResponse>(`/tasks/${taskId}`),

  cancel: (taskId: string) =>
    api.post<TaskStatusResponse>(`/tasks/${taskId}/cancel`),

  retry: (taskId: string) =>
    api.post<TaskStatusResponse>(`/tasks/${taskId}/retry`),

  artifacts: (taskId: string) =>
    api.get<TaskArtifactsResponse>(`/tasks/${taskId}/artifacts`),

  result: (taskId: string) =>
    api.get<TaskResultResponse>(`/tasks/${taskId}/result`),

  subscribeEvents: (
    taskId: string,
    onEvent: (event: RuntimeEventResponse) => void,
    onDone?: (task: TaskStatusResponse) => void,
    onError?: (error: Event) => void,
    afterSequence = 0,
  ): (() => void) => {
    const query = afterSequence > 0 ? `?after_sequence=${afterSequence}` : ''
    const source = new EventSource(
      `${API_BASE}/tasks/${encodeURIComponent(taskId)}/events${query}`,
    )

    source.addEventListener('runtime', (message) => {
      try {
        onEvent(JSON.parse(message.data) as RuntimeEventResponse)
      } catch {
        // Ignore malformed server events; TaskStatus polling remains authoritative.
      }
    })
    source.addEventListener('done', (message) => {
      source.close()
      try {
        onDone?.(JSON.parse(message.data) as TaskStatusResponse)
      } catch {
        // The stream is already complete even if its final snapshot is malformed.
      }
    })
    source.onerror = (error) => {
      source.close()
      onError?.(error)
    }

    return () => source.close()
  },
}
