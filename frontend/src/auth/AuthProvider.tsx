import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { fetchMe, login as apiLogin, logout as apiLogout, type MeResult } from '../api/auth'
import { getToken, setToken } from '../api/client'

interface AuthContextValue {
  token: string | null
  user: MeResult | null
  /** 首次校验会话是否完成，未完成时不要渲染受保护路由。 */
  ready: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken())
  const [user, setUser] = useState<MeResult | null>(null)
  const [ready, setReady] = useState(false)

  // 有 token 时校验会话并取回角色权限；失效则清理本地状态。
  useEffect(() => {
    if (!token) {
      setUser(null)
      setReady(true)
      return
    }
    let alive = true
    setReady(false)
    fetchMe()
      .then((me) => {
        if (alive) setUser(me)
      })
      .catch(() => {
        if (!alive) return
        setToken(null)
        setTokenState(null)
        setUser(null)
      })
      .finally(() => {
        if (alive) setReady(true)
      })
    return () => {
      alive = false
    }
  }, [token])

  // 任意请求遇到 401 时统一登出。
  useEffect(() => {
    const onUnauthorized = () => {
      setToken(null)
      setTokenState(null)
      setUser(null)
    }
    window.addEventListener('erp:unauthorized', onUnauthorized)
    return () => window.removeEventListener('erp:unauthorized', onUnauthorized)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiLogin({ username, password })
    setToken(res.access_token)
    setTokenState(res.access_token)
    const me = await fetchMe()
    setUser(me)
  }, [])

  const logout = useCallback(async () => {
    try {
      await apiLogout()
    } catch {
      // 会话可能已失效，仍要清理本地状态。
    }
    setToken(null)
    setTokenState(null)
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ token, user, ready, login, logout }),
    [token, user, ready, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}
