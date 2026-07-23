import { api } from './client'
import type {
  TaskArtifactsResponse,
  TaskListResponse,
  TaskResultResponse,
  TaskStatusResponse,
} from './types'

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
}
