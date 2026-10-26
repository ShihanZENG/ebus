import axios from 'axios'
import http from './http.ts'
export { getToken, setToken } from './http.ts'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}
type Params = Record<string, string | number | boolean | undefined | null>
interface RequestOptions {
  method?: string
  body?: unknown
  params?: Params
}

function query(params?: Params): URLSearchParams {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== '') search.append(key, String(value))
  }
  return search
}
function parse(text: string): unknown {
  if (!text) return null
  try { return JSON.parse(text) } catch { return text }
}
async function send(path: string, options: RequestOptions, download: boolean) {
  const { method = 'GET', body, params } = options
  try {
    return await http.request({
      url: path, method, params: query(params),
      data: body === undefined ? undefined : JSON.stringify(body),
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      responseType: download ? 'arraybuffer' : 'text',
      transformResponse: [(data: unknown) => data],
    })
  } catch (error) {
    if (!axios.isAxiosError(error) || !error.response) throw error
    const { status, data } = error.response
    if (status === 401) throw new ApiError(401, '登录已失效，请重新登录')
    const text = typeof data === 'string' ? data : new TextDecoder().decode(data)
    const payload = parse(text) as { error?: { message?: unknown }; detail?: unknown } | null
    const fallback = `请求失败（${status}）`
    const raw = payload?.error?.message ?? payload?.detail ?? fallback
    throw new ApiError(status, typeof raw === 'string' ? raw : download ? fallback : JSON.stringify(raw))
  }
}
/** Typed facade; callers own their error notifications. */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options, false)
  return (response.status === 204 ? undefined : parse(response.data)) as T
}
export async function requestBlob(path: string, params?: Params): Promise<Blob> {
  const response = await send(path, { params }, true)
  return new Blob([response.data], { type: String(response.headers['content-type'] ?? '') })
}
