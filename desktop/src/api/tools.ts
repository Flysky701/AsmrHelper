import { api } from './client'
import type {
  TaskStatusResponse,
  ToolListResponse,
  ToolTaskCreateRequest,
  TaskResultResponse,
} from './types'

export const toolsApi = {
  list: () => api.get<ToolListResponse>('/tool-runs'),

  create: (body: ToolTaskCreateRequest) =>
    api.post<TaskStatusResponse>('/tool-runs/tasks', body),

  result: (taskId: string) =>
    api.get<TaskResultResponse>(`/tool-runs/${taskId}`),
}
