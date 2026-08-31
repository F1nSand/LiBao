import type { ChatRequest, SseEnvelope } from '@/types'
import { SseParser, SeqGuard } from '@/utils/sse-parser'
import { markUnavailableForUrl } from './availability'

/**
 * SSE 客户端：fetch + ReadableStream（《02》前端设计 §5.2 / 《02》接口契约 §3）。
 * POST 流式（支持鉴权头 + body），不用 EventSource（仅 GET）。
 */

export interface SseHandlers {
  onEvent: (ev: SseEnvelope) => void
  onError?: (e: Error) => void
  /** 流正常关闭（含 EOF 无业务终态 = 半截 body）。info 由调用方判断断线语义；旧调用方不传参保持兼容。 */
  onClose?: (info?: { hadEvents: boolean; lastSeq: number; lastTaskSeq: number | undefined }) => void
}

/** 请求尚未进入 SSE 流时的 REST/HTTP 错误，保留服务端诊断字段供恢复事务判断。 */
export class SseRequestError extends Error {
  readonly status?: number
  readonly code?: number
  readonly traceId?: string

  constructor(message: string, fields: { status?: number; code?: number; traceId?: string } = {}) {
    super(message)
    this.name = 'SseRequestError'
    this.status = fields.status
    this.code = fields.code
    this.traceId = fields.traceId
  }
}

/** 传输层断线（网络错误/流中断）；HTTP 非 2xx 仍走 SseRequestError。 */
export class SseTransportError extends Error {
  readonly kind: 'network' | 'http'
  readonly status?: number
  readonly traceId?: string
  /** 断线前是否已交付过事件（区分首帧前断线） */
  readonly hadEvents: boolean
  /** 本连接内已交付的最大连接 seq */
  readonly lastSeq: number
  /** 本连接内已交付的最大 task_seq（跨连接游标） */
  readonly lastTaskSeq: number | undefined

  constructor(
    message: string,
    fields: { kind?: 'network' | 'http'; status?: number; traceId?: string; hadEvents?: boolean; lastSeq?: number; lastTaskSeq?: number } = {},
  ) {
    super(message)
    this.name = 'SseTransportError'
    this.kind = fields.kind ?? 'network'
    this.status = fields.status
    this.traceId = fields.traceId
    this.hadEvents = fields.hadEvents ?? false
    this.lastSeq = fields.lastSeq ?? 0
    this.lastTaskSeq = fields.lastTaskSeq
  }
}

interface OpenSseInit {
  method: string
  headers: Record<string, string>
  body?: string
  signal?: AbortSignal
}

/** 通用 SSE 流：读 body → 逐帧解析 → seq 去重 → 回调 */
export async function openSseStream(url: string, init: OpenSseInit, h: SseHandlers): Promise<void> {
  let resp: Response
  try {
    resp = await fetch(url, { ...init, signal: init.signal })
  } catch (e) {
    // fetch 拒绝 = 首帧前断线（连接未建立/网络立即失败）
    h.onError?.(new SseTransportError(e instanceof Error ? e.message : String(e), { kind: 'network', hadEvents: false, lastSeq: 0 }))
    return
  }

  if (!resp.ok || !resp.body) {
    // 端点未实现（HTTP 404）→ 打标，供页面优雅降级 + 停止 SSE 重连
    if (resp.status === 404) markUnavailableForUrl(url)
    h.onError?.(await responseError(resp))
    return
  }

  // 真实后端非流式语义（如 resume 返回 JSON 信封）→ 交由调用方处理
  if (resp.headers.get('content-type')?.includes('application/json')) {
    try {
      const body = await resp.json() as { code?: number; message?: string; trace_id?: string; type?: string }
      // REST 信封不是 SSE 事件，尤其不能把 code!=0 的错误当成业务帧交给状态机。
      if (typeof body.code === 'number' && body.code !== 0) {
        throw new SseRequestError(body.message || `stream failed: ${resp.status}`, {
          status: resp.status,
          code: body.code,
          traceId: body.trace_id,
        })
      }
      if (body.type) h.onEvent(body as SseEnvelope)
    } catch (e) {
      h.onError?.(e instanceof Error ? e : new SseRequestError(String(e), { status: resp.status }))
    } finally {
      h.onClose?.()
    }
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  const parser = new SseParser()
  const guard = new SeqGuard()
  let eventCount = 0
  let lastTaskSeq: number | undefined

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      for (const ev of parser.push(decoder.decode(value, { stream: true }))) {
        if (guard.accept(ev.seq)) {
          eventCount += 1
          if (typeof ev.task_seq === 'number') lastTaskSeq = ev.task_seq
          h.onEvent(ev)
        }
      }
    }
  } catch (e) {
    // 半路断流（网络中断 / 服务端 destroy socket）
    h.onError?.(new SseTransportError(e instanceof Error ? e.message : String(e), {
      kind: 'network',
      hadEvents: eventCount > 0,
      lastSeq: guard.current(),
      lastTaskSeq,
    }))
    return
  } finally {
    await reader.cancel().catch(() => {})
  }

  for (const ev of parser.end()) {
    if (guard.accept(ev.seq)) {
      eventCount += 1
      if (typeof ev.task_seq === 'number') lastTaskSeq = ev.task_seq
      h.onEvent(ev)
    }
  }
  h.onClose?.({ hadEvents: eventCount > 0, lastSeq: guard.current(), lastTaskSeq })
}

async function responseError(resp: Response): Promise<SseRequestError> {
  let message = `stream failed: ${resp.status}`
  let code: number | undefined
  let traceId: string | undefined
  try {
    const contentType = resp.headers.get('content-type') || ''
    if (contentType.includes('json')) {
      const body = await resp.clone().json() as { message?: string; code?: number; trace_id?: string }
      message = body.message || message
      code = body.code
      traceId = body.trace_id
    } else {
      const text = (await resp.clone().text()).trim()
      if (text) message = text
    }
  } catch {
    // 代理返回空 body 时保留稳定的 HTTP 文案。
  }
  return new SseRequestError(message, { status: resp.status, code, traceId })
}

/** 对话流式：POST 到指定 SSE 端点（chat/stream / tasks/{id}/resume） */
export async function streamChatAt(
  url: string,
  req: ChatRequest,
  h: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return openSseStream(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(req),
    signal,
  }, h)
}

/** 中断恢复续流：POST /api/v1/tasks/{id}/resume（《02》接口契约 §5.3） */
export async function streamTaskResume(
  taskId: string,
  confirm: Record<string, unknown>,
  h: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return openSseStream(`/api/v1/tasks/${taskId}/resume`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ confirm }),
    signal,
  }, h)
}

/** 任务事件订阅（长任务断线恢复）：先补发 task_seq > afterSeq 的持久化边界事件，再 live-tail。 */
export async function streamTaskEvents(
  taskId: string,
  opts: { afterSeq?: number; signal?: AbortSignal },
  h: SseHandlers,
): Promise<void> {
  const after = opts.afterSeq ? `?after_seq=${opts.afterSeq}` : ''
  return openSseStream(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/events${after}`,
    { method: 'GET', headers: { Accept: 'text/event-stream' }, signal: opts.signal },
    h,
  )
}
