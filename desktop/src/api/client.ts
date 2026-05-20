const API_BASE = 'http://localhost:8000/api/v1'

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
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })

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
  delete: <T>(path: string) => request<T>('DELETE', path),
}
