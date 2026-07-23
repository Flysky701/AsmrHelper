const DEFAULT_API_BASE = 'http://127.0.0.1:8000/api/v1'
const API_BASE = import.meta.env.VITE_API_BASE?.trim() || DEFAULT_API_BASE

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
    res = await fetch(`${API_BASE}${path}`, {
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
    const err = await res
      .json()
      .catch(() => ({ error: { code: 'UNKNOWN', message: res.statusText } }))
    throw new ApiError(
      err.error?.code ?? 'UNKNOWN',
      err.error?.message ?? res.statusText,
      res.status,
    )
  }

  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
