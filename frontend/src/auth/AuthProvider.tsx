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
  /** DEV 自动登录进行中：此期间 Guard 不跳转登录页，避免自动登录未完成的瞬间被弹到 /login。 */
  booting: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken())
  const [user, setUser] = useState<MeResult | null>(null)
  const [ready, setReady] = useState(false)
  const [booting, setBooting] = useState(false)

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
    // DEV：记住本次为主动登出，避免刷新后自动登录又把用户登回去。
    if (import.meta.env.DEV) sessionStorage.setItem('erp_dev_explicit_logout', '1')
  }, [])

  // DEV 便捷：演示环境打开即自动用注入的演示账号登录，
  // 避免每次手动登录才能看到真实数据。生产构建中 __LOCAL_DEMO_CREDENTIALS__ 为 null，不会触发。
  useEffect(() => {
    if (!import.meta.env.DEV || !__LOCAL_DEMO_CREDENTIALS__ || getToken()) return
    // 用户已主动登出过（同标签页内），不再自动登录。
    if (sessionStorage.getItem('erp_dev_explicit_logout')) return
    setBooting(true)
    login(__LOCAL_DEMO_CREDENTIALS__.username, __LOCAL_DEMO_CREDENTIALS__.password)
      .catch(() => {
        /* 自动登录失败不阻塞页面，用户仍可手动登录 */
      })
      .finally(() => {
        setBooting(false)
      })
  }, [login])

  const value = useMemo(
    () => ({ token, user, ready, booting, login, logout }),
    [token, user, ready, booting, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}
