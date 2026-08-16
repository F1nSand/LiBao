import { describe, it, expect, vi, afterEach } from 'vitest'
import { openSseStream } from './sse'
import type { SseHandlers } from './sse'
import type { SseEnvelope } from '@/types'
import { resetUnavailable, isUnavailable, FEATURE } from './availability'
import { useSSE } from '@/composables/useSSE'
import { effectScope } from 'vue'

function makeStream(chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(new TextEncoder().encode(c))
      controller.close()
    },
  })
}

function mkEnv(seq: number, text: string): SseEnvelope {
  return { id: `evt_${seq}`, seq, type: 'token', ts: 1700000000000, payload: { text } }
}

function sseFrame(seq: number, text: string): string {
  return `event: token\ndata: ${JSON.stringify(mkEnv(seq, text))}\n\n`
}

describe('openSseStream', () => {
  it('逐块解析并回调事件，跨 UTF-8 字符边界不丢字', async () => {
    const frame1 = sseFrame(1, '你好世界')
    const bytes = new TextEncoder().encode(frame1)
    // 故意在 UTF-8 字符中间切分（"世"占 3 字节）
    const cut = Math.floor(bytes.length * 0.6)
    const chunkA = bytes.slice(0, cut)
    const chunkB = bytes.slice(cut)

    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(chunkA)
        controller.enqueue(chunkB)
        controller.close()
      },
    })

    const events: SseEnvelope[] = []
    const handlers: SseHandlers = { onEvent: (ev) => events.push(ev) }
    const origFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: stream,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
    })

    await openSseStream('/x', { method: 'POST', headers: {} }, handlers)
    globalThis.fetch = origFetch

    expect(events).toHaveLength(1)
    expect((events[0].payload as { text: string }).text).toBe('你好世界')
  })

  it('非 2xx 触发 onError', async () => {
    const origFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500, body: null })
    const onError = vi.fn()
    await openSseStream('/x', { method: 'POST', headers: {} }, { onEvent: () => {}, onError })
    globalThis.fetch = origFetch
    expect(onError).toHaveBeenCalled()
  })

  it('多帧一次回调多个事件', async () => {
    const stream = makeStream([sseFrame(1, 'a') + sseFrame(2, 'b') + sseFrame(3, 'c')])
    const events: SseEnvelope[] = []
    const origFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: stream,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
    })
    await openSseStream('/x', { method: 'POST', headers: {} }, { onEvent: (ev) => events.push(ev) })
    globalThis.fetch = origFetch
    expect(events.map((e) => e.seq)).toEqual([1, 2, 3])
  })

  it('重复 seq 被去重（SeqGuard）', async () => {
    const stream = makeStream([sseFrame(1, 'a') + sseFrame(1, 'dup') + sseFrame(2, 'b')])
    const events: SseEnvelope[] = []
    const origFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: stream,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
    })
    await openSseStream('/x', { method: 'POST', headers: {} }, { onEvent: (ev) => events.push(ev) })
    globalThis.fetch = origFetch
    expect(events.map((e) => e.seq)).toEqual([1, 2])
  })

  it('HTTP 404（端点未实现）→ 打标对应 feature 且触发 onError', async () => {
    resetUnavailable()
    const origFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404, body: null })
    const onError = vi.fn()
    await openSseStream(
      '/api/v1/notifications/stream',
      { method: 'GET', headers: {} },
      { onEvent: () => {}, onError },
    )
    globalThis.fetch = origFetch
    expect(onError).toHaveBeenCalled()
    // SSE 流与 REST 列表是独立 feature：SSE 404 只标记 stream，不影响 REST 列表
    expect(isUnavailable(FEATURE.notificationsStream)).toBe(true)
    expect(isUnavailable(FEATURE.notifications)).toBe(false)
  })
})

describe('useSSE 降级防护', () => {
  afterEach(() => {
    vi.useRealTimers()
    resetUnavailable()
  })

  it('端点 404 打标后，即使 retryable=true 也不重连', async () => {
    vi.useFakeTimers()
    const origFetch = globalThis.fetch
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404, body: null })
    globalThis.fetch = fetchMock
    const onError = vi.fn()
    const scope = effectScope()

    await scope.run(async () => {
      const sse = useSSE(
        '/api/v1/notifications/stream',
        () => ({ method: 'GET', headers: {} }),
        { onEvent: () => {}, onError },
        { retryable: true },
      )
      await sse.connect()
      expect(onError).toHaveBeenCalled()
      // 若未短路会按退避重连 → fetch 次数 >1；这里应保持 1 次
      await vi.advanceTimersByTimeAsync(20_000)
    })

    globalThis.fetch = origFetch
    scope.stop()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
