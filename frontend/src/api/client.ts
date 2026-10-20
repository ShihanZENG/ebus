const BASE = '/api/v1'
const TOKEN_KEY = 'erp_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

interface RequestOptions {
  method?: string
  body?: unknown
  params?: Record<string, string | number | boolean | undefined | null>
}

/** 统一请求入口：注入 token、解析后端 { error: { message } } 结构、401 时广播失效事件。 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, params } = options
  let url = BASE + path

  if (params) {
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === '') continue
      search.append(key, String(value))
    }
    const qs = search.toString()
    if (qs) url += `?${qs}`
  }

  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (res.status === 401) {
    setToken(null)
    window.dispatchEvent(new Event('erp:unauthorized'))
    throw new ApiError(401, '登录已失效，请重新登录')
  }
  if (res.status === 204) return undefined as T

  const text = await res.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!res.ok) {
    const payload = data as { error?: { message?: unknown }; detail?: unknown } | null
    const raw = payload?.error?.message ?? payload?.detail ?? `请求失败（${res.status}）`
    throw new ApiError(res.status, typeof raw === 'string' ? raw : JSON.stringify(raw))
  }

  return data as T
}
