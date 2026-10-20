import axios from 'axios'
import { message } from 'antd'
import { getToken, setToken } from './api/client'

/**
 * 业务页面统一使用的 axios 实例。
 * token 读写复用 api/client.ts 的存取函数，避免多套存储键导致登录态不一致。
 */
const api = axios.create({ baseURL: '/api/v1' })

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      setToken(null)
      window.dispatchEvent(new Event('erp:unauthorized'))
      return Promise.reject(err)
    }
    const data = err.response?.data
    const msg = data?.error?.message || err.message
    message.error(msg)
    return Promise.reject(err)
  },
)

export default api
