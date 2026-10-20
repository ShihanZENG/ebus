import axios from 'axios'

const api = axios.create({
  baseURL: 'http://127.0.0.1:18090/api/v1',
  timeout: 20000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('oms_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error.response?.status
    if (status === 401) {
      localStorage.removeItem('oms_token')
      localStorage.removeItem('oms_user')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    const data = error.response?.data
    let message = '请求失败'
    if (data?.error?.message) message = data.error.message
    else if (data?.detail) message = data.detail
    else if (error.message) message = error.message
    return Promise.reject(new Error(message))
  },
)

export default api
