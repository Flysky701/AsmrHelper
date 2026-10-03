import { api } from './client'
import type {
  ModelSummaryResponse,
  ModelStatusResponse,
  ModelInstallRequest,
  TaskStatusResponse,
  ModelVerificationResponse,
} from './types'

export const modelsApi = {
  list: () => api.get<ModelSummaryResponse[]>('/models'),

  status: (modelId: string) => api.get<ModelStatusResponse>(`/models/${encodeURIComponent(modelId)}/status`),

  statuses: () =>
    api.get<ModelStatusResponse[]>('/models/statuses'),

  install: (modelId: string, body?: ModelInstallRequest) =>
    api.post<TaskStatusResponse>(`/models/${modelId}/install`, body),

  verify: (modelId: string) =>
    api.post<ModelVerificationResponse[]>(`/models/${modelId}/verify`),

}
