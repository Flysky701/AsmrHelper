import { api } from './client'
import type {
  ModelSummaryResponse,
  ModelStatusResponse,
  ModelOperationResponse,
  ModelInstallRequest,
  ModelInstallAsyncResponse,
  ModelVerificationResponse,
  TaskStatusResponse,
} from './types'

const DEFAULT_API_BASE = 'http://127.0.0.1:8000/api/v1'
const API_BASE = import.meta.env.VITE_API_BASE?.trim() || DEFAULT_API_BASE

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
    api.post<ModelVerificationResponse>(`/models/${modelId}/verify`),

  remove: (modelId: string) =>
    api.delete<ModelOperationResponse>(`/models/${modelId}`),

  unload: (modelId: string) =>
    api.post<ModelOperationResponse>(`/models/${modelId}/unload`),

  unloadAll: () =>
    api.post<ModelOperationResponse>('/models/unload-all'),

  /**
   * Subscribe to model install progress via SSE.
   * Returns an unsubscribe function.
   */
  subscribeInstallProgress: (
    taskId: string,
    onProgress: (task: TaskStatusResponse) => void,
    onDone?: () => void,
    onError?: (err: Event) => void,
  ): (() => void) => {
    const es = new EventSource(`${API_BASE}/tasks/${taskId}/events`)

    es.onmessage = (event) => {
      try {
        const task = JSON.parse(event.data) as TaskStatusResponse
        onProgress(task)
      } catch {
        // ignore parse errors
      }
    }

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
