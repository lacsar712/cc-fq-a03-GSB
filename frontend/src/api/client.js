import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const api = axios.create({
  baseURL: '/api',
  timeout: 20000,
})

api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') {
      err.message = detail
    } else if (Array.isArray(detail)) {
      err.message = detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
    }
    return Promise.reject(err)
  },
)

export async function login(username, password) {
  const { data } = await api.post('/auth/login', { username, password })
  return data
}

export async function getHealth() {
  const { data } = await api.get('/health')
  return data
}

export async function listSamples() {
  const { data } = await api.get('/samples')
  return data
}

export async function listJobs() {
  const { data } = await api.get('/jobs')
  return data
}

export async function getJob(id) {
  const { data } = await api.get(`/jobs/${id}`)
  return data
}

export async function getJobStages(id) {
  const { data } = await api.get(`/jobs/${id}/stages`)
  return data
}

export async function createJob(body) {
  const { data } = await api.post('/jobs', body)
  return data
}

// ---- 耗时台 / 超时门禁（数值均由服务端计算返回）----

export async function getTimeoutConfigs() {
  const { data } = await api.get('/timing/config')
  return data
}

export async function updateTimeoutConfigs(items) {
  const { data } = await api.put('/timing/config', { items })
  return data
}

export async function getTimingOverview(windowSize = 10) {
  const { data } = await api.get('/timing/overview', { params: { window: windowSize } })
  return data
}

export async function getTimeoutJobs() {
  const { data } = await api.get('/timing/timeouts')
  return data
}

export async function getJobTiming(id) {
  const { data } = await api.get(`/jobs/${id}/timing`)
  return data
}

export default api
