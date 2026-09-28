import { api } from './client'
import type {
  TaskStatusResponse,
  ToolListResponse,
  ToolTaskCreateRequest,
} from './types'

export const toolsApi = {
  list: () => api.get<ToolListResponse>('/tools'),

  create: (body: ToolTaskCreateRequest) =>
    api.post<TaskStatusResponse>('/tool-runs', body),

}
