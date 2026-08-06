import { api, apiUrl } from './client'
import type {
  RuntimeEventResponse,
  TaskArtifactsResponse,
  TaskListResponse,
  TaskResultResponse,
  TaskSpecResponse,
  TaskStatusResponse,
} from './types'

export const tasksApi = {
  list: () => api.get<TaskListResponse>('/tasks'),

  get: (taskId: string) =>
    api.get<TaskStatusResponse>(`/tasks/${taskId}`),

  spec: (taskId: string) =>
    api.get<TaskSpecResponse>(`/tasks/${taskId}/spec`),

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
      apiUrl(`/tasks/${encodeURIComponent(taskId)}/events${query}`),
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
