import { api } from './client'
import type {
  ModelSummaryResponse,
  ModelStatusResponse,
  ModelOperationResponse,
  ModelInstallRequest,
  ModelVerificationResponse,
} from './types'

export const modelsApi = {
  list: () => api.get<ModelSummaryResponse[]>('/models'),

  statuses: () =>
    api.get<ModelStatusResponse[]>('/models/statuses'),

  status: (modelId: string) =>
    api.get<ModelStatusResponse>(`/models/${modelId}/status`),

  install: (modelId: string, body?: ModelInstallRequest) =>
    api.post<ModelOperationResponse>(`/models/${modelId}/install`, body),

  verify: (modelId: string) =>
    api.post<ModelVerificationResponse>(`/models/${modelId}/verify`),

  remove: (modelId: string) =>
    api.delete<ModelOperationResponse>(`/models/${modelId}`),

  unload: (modelId: string) =>
    api.post<ModelOperationResponse>(`/models/${modelId}/unload`),

  unloadAll: () =>
    api.post<ModelOperationResponse>('/models/unload-all'),
}
