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

  runtime: (modelId: string) =>
    api.post<TaskStatusResponse>(`/models/${encodeURIComponent(modelId)}/runtime`),

  download: (modelId: string, body?: { install_mode?: string }) =>
    api.post<TaskStatusResponse>(`/models/${encodeURIComponent(modelId)}/download`, body),

  sources: () => api.get<{ roots: string[] }>('/models/sources'),
  addSource: (path: string) => api.post<{ roots: string[] }>('/models/sources', { path }),
  removeSource: (path: string) => api.post<{ roots: string[] }>('/models/sources/remove', { path }),
  scan: () => api.post<{ found: Array<{ model_id: string; path: string }> }>('/models/scan'),

  install: (modelId: string, body?: ModelInstallRequest) =>
    api.post<TaskStatusResponse>(`/models/${modelId}/install`, body),

  verify: (modelId: string) =>
    api.post<ModelVerificationResponse[]>(`/models/${modelId}/verify`),

}
