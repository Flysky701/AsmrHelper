import { api } from './client'
import type {
  BatchDiscoverResponse,
  BatchRunCreateRequest,
  GraphBatchRunCreateRequest,
  BatchRunListResponse,
  BatchRunResponse,
} from './types'

export const batchesApi = {
  discover: (directory: string, recursive = true, limit?: number, media_kind: 'audio' | 'subtitle' | 'all' = 'audio') =>
    api.post<BatchDiscoverResponse>('/batch-runs/discover', { directory, recursive, limit, media_kind }),

  create: (body: BatchRunCreateRequest | GraphBatchRunCreateRequest) =>
    api.post<BatchRunResponse>('/batch-runs', body),

  list: () => api.get<BatchRunListResponse>('/batch-runs'),

  get: (batchId: string) =>
    api.get<BatchRunResponse>(`/batch-runs/${encodeURIComponent(batchId)}`),

  cancel: (batchId: string) =>
    api.post<BatchRunResponse>(`/batch-runs/${encodeURIComponent(batchId)}/cancel`),

  retryFailed: (batchId: string) =>
    api.post<BatchRunResponse>(`/batch-runs/${encodeURIComponent(batchId)}/retry-failed`),
}
