import { API_BASE, ApiError, api, apiUrl } from './client'
import type {
  DraftCommitRequest,
  DraftCommitResponse,
  DraftDetail,
  DraftListResponse,
  DraftPatchRequest,
  DraftState,
  DraftSummary,
  DraftSegment,
  DraftSegmentEdit,
  OverSpeedCueItem,
  QualityAuditReport,
} from './types'

export type {
  DraftCommitRequest,
  DraftCommitResponse,
  DraftDetail,
  DraftListResponse,
  DraftPatchRequest,
  DraftState,
  DraftSummary,
  DraftSegment,
  DraftSegmentEdit,
  OverSpeedCueItem,
  QualityAuditReport,
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(apiUrl(path), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown network error'
    throw new ApiError('NETWORK_ERROR', `Cannot connect to backend at ${API_BASE}: ${message}`, 0)
  }

  if (!res.ok) {
    const err = await res.json().catch(() => null)
    const error = err?.error
    const detail = err?.detail
    const detailMessage =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: { msg?: string }) => item?.msg).filter(Boolean).join('; ')
          : undefined
    const message =
      error?.message ??
      err?.message ??
      detailMessage ??
      res.statusText ??
      `HTTP ${res.status}`
    throw new ApiError(
      error?.code ?? err?.code ?? `HTTP_${res.status}`,
      message || `HTTP ${res.status}`,
      res.status,
    )
  }

  if (res.status === 204 || res.headers.get('content-length') === '0') {
    return undefined as T
  }

  const text = await res.text()
  if (!text) return undefined as T

  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError(
      'INVALID_RESPONSE',
      `Backend returned a non-JSON response for PATCH ${path}`,
      res.status,
    )
  }
}

export interface DraftListParams {
  state?: DraftState
  limit?: number
}

export const draftsApi = {
  list: (params?: DraftListParams) => {
    const search = new URLSearchParams()
    if (params?.state) search.set('state', params.state)
    if (typeof params?.limit === 'number') search.set('limit', String(params.limit))
    const qs = search.toString()
    return api.get<DraftListResponse>(qs ? `/drafts?${qs}` : '/drafts')
  },

  get: (draftId: string) =>
    api.get<DraftDetail>(`/drafts/${encodeURIComponent(draftId)}`),

  getAudit: (draftId: string) =>
    api.get<QualityAuditReport>(`/drafts/${encodeURIComponent(draftId)}/audit`),

  patch: (draftId: string, body: DraftPatchRequest) =>
    patchJson<DraftDetail>(`/drafts/${encodeURIComponent(draftId)}`, body),

  commit: (draftId: string, body: DraftCommitRequest) =>
    api.post<DraftCommitResponse>(`/drafts/${encodeURIComponent(draftId)}/commit`, body),
}
