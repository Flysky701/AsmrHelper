export const DEFAULT_API_BASE = 'http://127.0.0.1:8000/api/v1'
export const API_BASE = import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/, '') || DEFAULT_API_BASE

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE}${normalizedPath}`
}

export class ApiError extends Error {
  code: string
  status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(apiUrl(path), {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown network error'
    throw new ApiError(
      'NETWORK_ERROR',
      `Cannot connect to backend at ${API_BASE}: ${message}`,
      0,
    )
  }

  if (!res.ok) {
    const err = await res.json().catch(() => null)
    const error = err?.error
    const detail = err?.detail
    const detailMessage =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item?.msg).filter(Boolean).join('; ')
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
      `Backend returned a non-JSON response for ${method} ${path}`,
      res.status,
    )
  }
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
