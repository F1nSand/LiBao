import type { ChatRequest, SseEnvelope } from '@/types'
import { getToken } from '@/utils/token'
import { SseParser, SeqGuard } from '@/utils/sse-parser'
import { markUnavailableForUrl } from './availability'

/**
 * SSE 客户端：fetch + ReadableStream（docs/02 §5.2 / docs/03 §3）。
 * POST 流式（支持鉴权头 + body），不用 EventSource（仅 GET）。
 */

export interface SseHandlers {
  onEvent: (ev: SseEnvelope) => void
  onError?: (e: Error) => void
  onClose?: () => void
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
    h.onError?.(e instanceof Error ? e : new Error(String(e)))
    return
  }

  if (!resp.ok || !resp.body) {
    // 端点未实现（HTTP 404）→ 打标，供页面优雅降级 + 停止 SSE 重连
    if (resp.status === 404) markUnavailableForUrl(url)
    h.onError?.(new Error(`stream failed: ${resp.status}`))
    return
  }

  // 真实后端非流式语义（如 resume 返回 JSON 信封）→ 交由调用方处理
  if (resp.headers.get('content-type')?.includes('application/json')) {
    try {
      const env = (await resp.json()) as SseEnvelope
      h.onEvent(env)
    } catch (e) {
      h.onError?.(e instanceof Error ? e : new Error(String(e)))
    } finally {
      h.onClose?.()
    }
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  const parser = new SseParser()
  const guard = new SeqGuard()

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      for (const ev of parser.push(decoder.decode(value, { stream: true }))) {
        if (guard.accept(ev.seq)) h.onEvent(ev)
      }
    }
  } catch (e) {
    h.onError?.(e instanceof Error ? e : new Error(String(e)))
    return
  } finally {
    await reader.cancel().catch(() => {})
  }

  for (const ev of parser.end()) {
    if (guard.accept(ev.seq)) h.onEvent(ev)
  }
  h.onClose?.()
}

/** 对话流式：POST /api/v1/chat/stream */
export async function streamChat(
  req: ChatRequest,
  h: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return streamChatAt('/api/v1/chat/stream', req, h, signal)
}

/** 流式到指定 URL（默认 POST /chat/stream；可传任意 SSE 端点） */
export async function streamChatAt(
  url: string,
  req: ChatRequest,
  h: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken()
  return openSseStream(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(req),
    signal,
  }, h)
}

/** 中断恢复续流：POST /api/v1/tasks/{id}/resume（docs/03 §5.3） */
export async function streamTaskResume(
  taskId: string,
  confirm: Record<string, unknown>,
  h: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken()
  return openSseStream(`/api/v1/tasks/${taskId}/resume`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ confirm }),
    signal,
  }, h)
}

/** 任务事件订阅：GET /api/v1/tasks/{id}/events（docs/03 §5.3，SSE） */
export function streamTaskEvents(
  taskId: string,
  h: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken()
  return openSseStream(`/api/v1/tasks/${taskId}/events`, {
    method: 'GET',
    headers: {
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    signal,
  }, h)
}
