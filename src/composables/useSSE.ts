import { onScopeDispose, ref, type Ref } from 'vue'
import { openSseStream, type SseHandlers } from '@/api/sse'
import { isUrlUnavailable } from '@/api/availability'

/**
 * 任务/通知等 SSE 订阅（docs/02 §5.1 FD-6）：
 * 封装生命周期（组件卸载断流）+ 失败指数退避重连。
 */
export function useSSE(
  url: string | Ref<string> | (() => string),
  initFactory: () => { method: string; headers: Record<string, string>; body?: string },
  handlers: Pick<SseHandlers, 'onEvent'> & Partial<Omit<SseHandlers, 'onEvent'>>,
  opts?: { retryable?: boolean; onRetryableError?: (e: Error) => boolean },
) {
  const connected = ref(false)
  let controller: AbortController | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let retryCount = 0

  function disconnect(): void {
    if (retryTimer) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
    controller?.abort()
    controller = null
    connected.value = false
  }

  async function connect(): Promise<void> {
    disconnect()
    const u = typeof url === 'string' ? url : typeof url === 'function' ? url() : url.value
    controller = new AbortController()
    const init = initFactory()
    await openSseStream(
      u,
      { ...init, signal: controller.signal },
      {
        onEvent: handlers.onEvent,
        onError: (e) => {
          connected.value = false
          handlers.onError?.(e)
          // 端点未实现（已打标）→ 不重连，避免对缺失接口无限重试
          if (isUrlUnavailable(u)) return
          const shouldRetry = opts?.onRetryableError ? opts.onRetryableError(e) : (opts?.retryable ?? false)
          if (shouldRetry && !controller?.signal.aborted) scheduleReconnect()
        },
        onClose: () => {
          connected.value = false
          handlers.onClose?.()
        },
      },
    )
  }

  function scheduleReconnect(): void {
    const backoff = Math.min(300 * 2 ** retryCount, 10_000)
    retryCount += 1
    retryTimer = setTimeout(() => void connect(), backoff)
  }

  function resetRetry(): void {
    retryCount = 0
  }

  onScopeDispose(disconnect)

  return { connect, disconnect, connected, resetRetry }
}
