import { api, apiUrl } from './client'
import type {
  ModelSummaryResponse,
  ModelStatusResponse,
  ModelOperationResponse,
  ModelInstallRequest,
  ModelInstallAsyncResponse,
  ModelVerificationResponse,
  RuntimeEventResponse,
} from './types'

export const modelsApi = {
  list: () => api.get<ModelSummaryResponse[]>('/models'),

  statuses: () =>
    api.get<ModelStatusResponse[]>('/models/statuses'),

  status: (modelId: string) =>
    api.get<ModelStatusResponse>(`/models/${modelId}/status`),

  install: (modelId: string, body?: ModelInstallRequest) =>
    api.post<ModelOperationResponse>(`/models/${modelId}/install?sync=true`, body),

  installAsync: (modelId: string, body?: ModelInstallRequest) =>
    api.post<ModelInstallAsyncResponse>(`/models/${modelId}/install`, body),

  verify: (modelId: string) =>
    api.post<ModelVerificationResponse[]>(`/models/${modelId}/verify`),

  remove: (modelId: string) =>
    api.delete<ModelOperationResponse>(`/models/${modelId}`),

  unload: (modelId: string) =>
    api.post<ModelOperationResponse>(`/models/${modelId}/unload`),

  unloadAll: () =>
    api.post<void>('/models/unload-all'),

  /**
   * Subscribe to model install progress via SSE.
   * Returns an unsubscribe function.
   */
  subscribeInstallProgress: (
    taskId: string,
    onProgress: (event: RuntimeEventResponse) => void,
    onDone?: () => void,
    onError?: (err: Event) => void,
  ): (() => void) => {
    const es = new EventSource(apiUrl(`/tasks/${encodeURIComponent(taskId)}/events`))

    es.addEventListener('runtime', (event) => {
      try {
        const runtimeEvent = JSON.parse(event.data) as RuntimeEventResponse
        onProgress(runtimeEvent)
      } catch {
        // ignore parse errors
      }
    })

    es.addEventListener('done', () => {
      es.close()
      onDone?.()
    })

    es.addEventListener('error', (err) => {
      es.close()
      onError?.(err)
    })

    return () => es.close()
  },
}
