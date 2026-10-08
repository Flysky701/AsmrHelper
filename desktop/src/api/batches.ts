import { api } from './client'
import type {
  BatchDiscoverResponse,
  BatchRunCreateRequest,
  GraphBatchRunCreateRequest,
  BatchRunListResponse,
  BatchRunResponse,
} from './types'

export type RemovableBatchRunResponse = Omit<BatchRunResponse, 'items'> & {
  items: Array<BatchRunResponse['items'][number] & { removed?: boolean }>
}

export const batchesApi = {
  discover: (directory: string, recursive = true, limit?: number, media_kind: 'audio' | 'subtitle' | 'all' = 'audio') =>
    api.post<BatchDiscoverResponse>('/batch-runs/discover', { directory, recursive, limit, media_kind }),

  create: (body: BatchRunCreateRequest | GraphBatchRunCreateRequest) =>
    api.post<BatchRunResponse>('/batch-runs', body),

  list: () => api.get<Omit<BatchRunListResponse, 'batches'> & { batches: RemovableBatchRunResponse[] }>('/batch-runs'),

  get: (batchId: string) =>
    api.get<RemovableBatchRunResponse>(`/batch-runs/${encodeURIComponent(batchId)}`),

  setItemRemoved: (batchId: string, itemId: string, expectedUpdatedAt: string, removed: boolean) =>
    api.post<RemovableBatchRunResponse>(`/batch-runs/${encodeURIComponent(batchId)}/items/${encodeURIComponent(itemId)}/removal`,
      { expected_updated_at: expectedUpdatedAt, removed }),

  cancel: (batchId: string) =>
    api.post<BatchRunResponse>(`/batch-runs/${encodeURIComponent(batchId)}/cancel`),

  retryFailed: (batchId: string) =>
    api.post<BatchRunResponse>(`/batch-runs/${encodeURIComponent(batchId)}/retry-failed`),
}
