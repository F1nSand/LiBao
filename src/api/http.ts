import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiEnvelope } from '@/types'
import { ApiError, unwrapEnvelope, isNotImplementedError } from '@/utils/http-envelope'
import { isUrlUnavailable, markUnavailableForUrl } from './availability'

const BASE_URL = '/api/v1'

// 模块级 token（不依赖 pinia，避免循环依赖；由 auth store 通过 setAuthToken 注入）
let authToken: string | null = null
let unauthorizedHandler: (() => void) | null = null

export function setAuthToken(token: string | null): void {
  authToken = token
}

export function onUnauthorized(cb: () => void): void {
  unauthorizedHandler = cb
}

export const http = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
})

http.interceptors.request.use((config) => {
  if (authToken) {
    config.headers.Authorization = `Bearer ${authToken}`
  }
  // FormData 由浏览器自带 boundary，不手动设 Content-Type
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type']
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    const body = response.data as ApiEnvelope
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 40101 || body.code === 40102) {
        handleUnauthorized()
      }
      return response
    }
    return response
  },
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      handleUnauthorized()
    }
    return Promise.reject(error)
  },
)

function handleUnauthorized(): void {
  if (unauthorizedHandler) unauthorizedHandler()
}

/**
 * 请求封装：自动解包信封，code!==0 抛 ApiError 并全局提示。
 * 对「端点未实现」（HTTP 404 / 信封未实现标记）打标到 availability 并静默 rethrow（不 toast），
 * 供页面按优雅降级处理。已确认未实现的功能在发请求前短路（ApiError 40401 不进 catch、不 toast）。
 */
export async function request<T>(url: string, make: () => Promise<{ data: ApiEnvelope<T> }>): Promise<T> {
  if (isUrlUnavailable(url)) {
    throw new ApiError(40401, '接口未实现')
  }
  try {
    const { data } = await make()
    return unwrapEnvelope<T>(data)
  } catch (e) {
    if (isNotImplementedError(e)) {
      markUnavailableForUrl(url)
      throw e
    }
    if (e instanceof ApiError) {
      if (e.code >= 400 && e.code !== 40101) {
        ElMessage.error(`${e.message}${e.traceId ? `（trace: ${e.traceId.slice(0, 8)}）` : ''}`)
      }
      throw e
    }
    throw e
  }
}

/** 供 API 模块使用的快捷方法 */
export const httpGet = <T>(url: string, config?: AxiosRequestConfig) =>
  request<T>(url, () => http.get<ApiEnvelope<T>>(url, config))

export const httpPost = <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
  request<T>(url, () => http.post<ApiEnvelope<T>>(url, data, config))

export const httpPut = <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
  request<T>(url, () => http.put<ApiEnvelope<T>>(url, data, config))

export const httpPatch = <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
  request<T>(url, () => http.patch<ApiEnvelope<T>>(url, data, config))

export const httpDelete = <T>(url: string, config?: AxiosRequestConfig) =>
  request<T>(url, () => http.delete<ApiEnvelope<T>>(url, config))

export { ApiError }
