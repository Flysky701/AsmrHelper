import { api } from './client'
import type { TaskListResponse, TaskStatusResponse } from './types'

export const tasksApi = {
  list: () => api.get<TaskListResponse>('/tasks'),

  get: (taskId: string) =>
    api.get<TaskStatusResponse>(`/tasks/${taskId}`),

  cancel: (taskId: string) =>
    api.post<TaskStatusResponse>(`/tasks/${taskId}/cancel`),

  retry: (taskId: string) =>
    api.post<TaskStatusResponse>(`/tasks/${taskId}/retry`),
}
