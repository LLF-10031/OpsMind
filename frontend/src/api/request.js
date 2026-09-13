import axios from 'axios'
import { ElMessage } from 'element-plus'
import { baseURL } from './base'

const request = axios.create({ baseURL, timeout: 60000 })

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('opsmind_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

const errMessage = (msg, code) => {
  ElMessage.error(`${code ? code + ': ' : ''}${msg}`)
}

request.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && typeof body === 'object' && 'success' in body) {
      if (body.success === false) {
        const code = body.error?.code || 'ERROR'
        errMessage(body.error?.message || '请求失败', code)
        return Promise.reject(new Error(code))
      }
      return body.data
    }
    return body
  },
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('opsmind_token')
      if (location.hash !== '#/login') {
        errMessage('登录已过期，请重新登录', 'UNAUTHORIZED')
        location.hash = '#/login'
      }
    } else {
      const detail = error.response?.data?.detail
      errMessage(detail || error.message || '网络错误')
    }
    return Promise.reject(error)
  }
)

export default request
