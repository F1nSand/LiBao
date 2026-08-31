import type { ApiEnvelope } from '@/types'

/** 业务错误：携带 code / trace_id / retryable（《02》接口契约 §2.3 错误码） */
export class ApiError extends Error {
  code: number
  traceId?: string
  retryable?: boolean

  constructor(code: number, message: string, traceId?: string, retryable?: boolean) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.traceId = traceId
    this.retryable = retryable
  }
}

/** 信封解包纯函数：code===0 返回 data，否则抛 ApiError */
export function unwrapEnvelope<T>(env: ApiEnvelope<T>): T {
  if (env.code !== 0) {
    throw new ApiError(env.code, env.message, env.trace_id, isRetryableCode(env.code))
  }
  return env.data
}

function isRetryableCode(code: number): boolean {
  // 500xx 服务端 / 600xx Agent 运行错误可重试；400xx/401xx/403xx/404xx/409xx/422xx/429xx 不可
  return code >= 500
}

/**
 * 判断错误是否为「端点未实现」（接真实后端时用于优雅降级）。
 * 真实后端未注册路由 → HTTP 404（FastAPI 默认，非信封）；业务 404xx → HTTP 200 + 信封，
 * 两者不重叠，故 HTTP 404 是可靠判别，不会误伤业务资源不存在。
 * 信封兜底：显式含「未实现」标记（mock 未命中 / 后端预留端点）。
 */
export function isNotImplementedError(e: unknown): boolean {
  if ((e as { response?: { status?: number } })?.response?.status === 404) return true
  if (e instanceof ApiError && /未实现|not implemented/i.test(e.message)) return true
  return false
}

/**
 * 未实现错误转 undefined（供 store action 优雅降级时静默），其余错误照常抛。
 * 配合 http 层打标：端点未实现时返回 undefined，调用方跳过赋值显示空态。
 */
export async function swallowNotImplemented<T>(p: Promise<T>): Promise<T | undefined> {
  try {
    return await p
  } catch (e) {
    if (isNotImplementedError(e)) return undefined
    throw e
  }
}
