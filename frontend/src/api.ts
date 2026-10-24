import { message } from 'antd'
import { createHttpClient } from './api/http'

/** Preserve Axios responses and business-page notifications without notifying typed callers. */
const api = createHttpClient()
api.interceptors.response.use(response => response, err => {
  if (err.response?.status !== 401) message.error(err.response?.data?.error?.message || err.message)
  return Promise.reject(err)
})
export default api
