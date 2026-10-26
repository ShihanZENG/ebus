import axios from 'axios'

const TOKEN_KEY = 'erp_token'
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

/** Shared transport; UI notifications belong to the caller. */
export function createHttpClient() {
  const client = axios.create({ baseURL: '/api/v1' })
  client.interceptors.request.use(config => {
    const token = getToken()
    if (token) config.headers.Authorization = `Bearer ${token}`
    return config
  })
  client.interceptors.response.use(response => response, error => {
    if (error.response?.status === 401) {
      setToken(null)
      window.dispatchEvent(new Event('erp:unauthorized'))
    }
    return Promise.reject(error)
  })
  return client
}
const http = createHttpClient()
export default http
