import { api } from './client'
import type {
  TaskResultResponse,
  TaskStatusResponse,
  ToolListResponse,
  ToolTaskCreateRequest,
} from './types'

export const toolsApi = {
  list: () => api.get<ToolListResponse>('/tool-runs'),

  create: (body: ToolTaskCreateRequest) =>
    api.post<TaskStatusResponse>('/tool-runs/tasks', body),

  run: (taskId: string) =>
    api.post<TaskResultResponse>('/tool-runs', { task_id: taskId }),

  result: (taskId: string) =>
    api.get<TaskResultResponse>(`/tool-runs/${taskId}`),
}
