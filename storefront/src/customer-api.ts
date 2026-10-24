export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

export type Customer = { id: string; username: string; display_name: string; phone: string; preferences: Record<string, string> }

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.method && options.method !== 'GET') headers.set('X-Storefront-Request', '1')
  const response = await fetch('/api/storefront/v1' + path, {
    ...options, headers, credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(20000),
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const field = data?.error?.fields?.[0]
    const fieldName = String(field?.field ?? '')
    const label = fieldName.includes('username') ? '用户名' : fieldName.includes('password') ? '密码' : fieldName.includes('postcode') ? '邮编' : fieldName.includes('email') ? '邮箱' : fieldName.includes('address') ? '收货地址' : '填写内容'
    const message = field ? `${label}：${String(field.message).replace(/^Value error, /, '')}` : data?.error?.message || data?.detail || `请求失败（${response.status}）`
    throw new ApiError(typeof message === 'string' ? message : '填写内容无效', response.status)
  }
  if (!data) throw new Error('服务返回内容无效，请重试')
  return data
}
export const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败，请稍后重试'
