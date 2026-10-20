import { request } from './client'

export interface LoginPayload {
  username: string
  password: string
}

export interface LoginResult {
  access_token: string
  token_type: string
  expires_at: string
}

/** /api/v1/auth/me 返回 public_user 字段，外加 role 与 permissions。 */
export interface MeResult {
  id: string
  username: string
  role: string
  permissions: string[]
  is_active: boolean
  shop_scope: string[] | null
  warehouse_scope: string[] | null
}

export const login = (payload: LoginPayload) =>
  request<LoginResult>('/auth/login', { method: 'POST', body: payload })

export const fetchMe = () => request<MeResult>('/auth/me')

export const logout = () => request<void>('/auth/logout', { method: 'POST' })
