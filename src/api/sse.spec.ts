import { describe, it, expect, vi, afterEach } from 'vitest'
import { openSseStream, SseRequestError, SseTransportError, streamTaskEvents } from './sse'
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

  it('REST 错误信封不冒充 SSE 事件，并保留业务 code/message', async () => {
    const origFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      body: null,
      headers: new Headers({ 'content-type': 'application/json' }),
      clone: () => ({ json: async () => ({ code: 40902, message: '当前会话仍有待确认操作', trace_id: 'tr_1' }) }),
    })
    const events: SseEnvelope[] = []
    let error: Error | undefined
    await openSseStream('/resume', { method: 'POST', headers: {} }, { onEvent: (ev) => events.push(ev), onError: (e) => { error = e } })
    globalThis.fetch = origFetch
    expect(events).toHaveLength(0)
    expect(error).toBeInstanceOf(SseRequestError)
    expect(error?.message).toContain('待确认')
    expect((error as SseRequestError).code).toBe(40902)
  })

  it('干净 EOF 无 done（半截 body）→ onClose 携带已交付信息，不触发 onError', async () => {
    const frame1 = `event: tool_call\ndata: ${JSON.stringify({ id: 'e1', seq: 1, task_seq: 5, type: 'tool_call', ts: 1, payload: { tool_call_id: 'tc1', tool_name: 'web_search', input: {} } })}\n\n`
    const frame2 = `event: token\ndata: ${JSON.stringify({ id: 'e2', seq: 2, type: 'token', ts: 2, payload: { text: '半截' } })}\n\n`
    const origFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: makeStream([frame1 + frame2]),
      headers: new Headers({ 'content-type': 'text/event-stream' }),
    })
    let closeInfo: { hadEvents: boolean; lastSeq: number; lastTaskSeq: number | undefined } | undefined
    const onError = vi.fn()
    await openSseStream('/x', { method: 'POST', headers: {} }, {
      onEvent: () => {},
      onError,
      onClose: (info) => { closeInfo = info },
    })
    globalThis.fetch = origFetch
    expect(onError).not.toHaveBeenCalled()
    expect(closeInfo).toEqual({ hadEvents: true, lastSeq: 2, lastTaskSeq: 5 })
  })

  it('流中断（reader.error）→ SseTransportError 带 hadEvents/lastSeq/lastTaskSeq', async () => {
    const chunks = [
      new TextEncoder().encode(sseFrame(1, 'a')),
      new TextEncoder().encode(`event: token\ndata: ${JSON.stringify({ id: 'e2', seq: 2, task_seq: 9, type: 'token', ts: 2, payload: { text: 'b' } })}\n\n`),
    ]
    let i = 0
    // ReadableStream 的 controller.error 会让后续 read 直接 reject 且丢弃队列，故用 fake reader 精确模拟半路断流
    const fakeReader = {
      read: async () => {
        if (i < chunks.length) return { done: false, value: chunks[i++] } as const
        throw new Error('net broken')
      },
      cancel: async () => {},
    }
    const origFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => fakeReader },
      headers: new Headers({ 'content-type': 'text/event-stream' }),
    })
    let error: Error | undefined
    await openSseStream('/x', { method: 'POST', headers: {} }, { onEvent: () => {}, onError: (e) => { error = e } })
    globalThis.fetch = origFetch
    expect(error).toBeInstanceOf(SseTransportError)
    const te = error as SseTransportError
    expect(te.kind).toBe('network')
    expect(te.hadEvents).toBe(true)
    expect(te.lastSeq).toBe(2)
    expect(te.lastTaskSeq).toBe(9)
  })

  it('fetch 拒绝（首帧前断线）→ SseTransportError hadEvents=false', async () => {
    const origFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('connection refused'))
    let error: Error | undefined
    await openSseStream('/x', { method: 'POST', headers: {} }, { onEvent: () => {}, onError: (e) => { error = e } })
    globalThis.fetch = origFetch
    expect(error).toBeInstanceOf(SseTransportError)
    const te = error as SseTransportError
    expect(te.kind).toBe('network')
    expect(te.hadEvents).toBe(false)
    expect(te.lastSeq).toBe(0)
  })

  it('task_seq 随事件透传', async () => {
    const frame = `event: status\ndata: ${JSON.stringify({ id: 'e1', seq: 1, task_seq: 42, type: 'status', ts: 1, payload: { status: 'running' } })}\n\n`
    const origFetch = globalThis.fetch
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: makeStream([frame]),
      headers: new Headers({ 'content-type': 'text/event-stream' }),
    })
    const events: SseEnvelope[] = []
    await openSseStream('/x', { method: 'GET', headers: {} }, { onEvent: (ev) => events.push(ev) })
    globalThis.fetch = origFetch
    expect(events).toHaveLength(1)
    expect(events[0].task_seq).toBe(42)
  })
})

describe('streamTaskEvents', () => {
  it('构造 GET /tasks/{id}/events?after_seq=N', async () => {
    const origFetch = globalThis.fetch
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: makeStream([sseFrame(1, 'a')]),
      headers: new Headers({ 'content-type': 'text/event-stream' }),
    })
    globalThis.fetch = fetchMock
    await streamTaskEvents('t1', { afterSeq: 7 }, { onEvent: () => {} })
    globalThis.fetch = origFetch
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tasks/t1/events?after_seq=7', expect.objectContaining({ method: 'GET' }))
  })

  it('无 afterSeq 时无 query 参数', async () => {
    const origFetch = globalThis.fetch
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: makeStream([sseFrame(1, 'a')]),
      headers: new Headers({ 'content-type': 'text/event-stream' }),
    })
    globalThis.fetch = fetchMock
    await streamTaskEvents('t2', {}, { onEvent: () => {} })
    globalThis.fetch = origFetch
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/tasks/t2/events', expect.objectContaining({ method: 'GET' }))
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
