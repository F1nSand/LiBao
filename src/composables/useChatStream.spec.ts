import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushNow } from '@/utils/rAF'
import type { SseEnvelope } from '@/types'
import type { SseHandlers } from '@/api/sse'

const { streamChat, streamTaskResume, streamTaskEvents, cancelTask, getTaskStatus, recoverTask } = vi.hoisted(() => ({
  streamChat: vi.fn(),
  streamTaskResume: vi.fn(),
  streamTaskEvents: vi.fn(),
  cancelTask: vi.fn(),
  getTaskStatus: vi.fn(),
  recoverTask: vi.fn(),
}))

vi.mock('@/api/sse', () => ({
  streamChat,
  streamChatAt: streamChat,
  streamTaskResume,
  streamTaskEvents,
}))
vi.mock('@/api/task-control', () => ({ cancelTask, getTaskStatus, recoverTask }))

import { useChatStream } from './useChatStream'

let chatHandlers: SseHandlers | null = null
let resumeHandlers: SseHandlers | null = null
let eventsHandlers: SseHandlers | null = null

function ev(type: string, seq: number, payload: unknown): SseEnvelope {
  return { id: `e${seq}`, seq, type: type as SseEnvelope['type'], ts: 1700000000000, payload }
}

/** 带 task_seq 的信封（长任务断线恢复契约：跨连接单调游标） */
function evSeq(type: string, seq: number, taskSeq: number, payload: unknown): SseEnvelope {
  return { ...ev(type, seq, payload), id: `task_evt_${taskSeq}`, task_seq: taskSeq }
}

function transportError(msg = 'net broken'): Error {
  const e = new Error(msg)
  e.name = 'SseTransportError'
  return e
}

const chatReq = {
  conversation_id: null,
  agent_id: 'ag_calc',
  message: { content: 'hi', role: 'user' },
  stream: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  chatHandlers = null
  resumeHandlers = null
  eventsHandlers = null
  streamChat.mockImplementation((_url: unknown, _req: unknown, h: SseHandlers) => {
    chatHandlers = h
    return Promise.resolve()
  })
  streamTaskResume.mockImplementation((_id: unknown, _c: unknown, h: SseHandlers) => {
    resumeHandlers = h
    return Promise.resolve()
  })
  streamTaskEvents.mockImplementation((_id: unknown, _opts: unknown, h: SseHandlers) => {
    eventsHandlers = h
    return Promise.resolve()
  })
  cancelTask.mockResolvedValue('cancelled')
  getTaskStatus.mockResolvedValue({ status: 'waiting_confirm' })
  recoverTask.mockResolvedValue({ task_id: 't1', status: 'running' })
})

describe('useChatStream 状态机', () => {
  it('message_start 带 checkpoint 锚点时回调字段映射准确', async () => {
    const onCheckpointAnchor = vi.fn()
    const cs = useChatStream({ onCheckpointAnchor })
    await cs.start(chatReq as never)

    chatHandlers!.onEvent(ev('message_start', 1, {
      message_id: 'assistant-1',
      agent_id: 'a',
      conversation_id: 'conversation-1',
      task_id: 'task-1',
      user_message_id: 'user-1',
      checkpoint_id: 'checkpoint-1',
    }))

    expect(onCheckpointAnchor).toHaveBeenCalledTimes(1)
    expect(onCheckpointAnchor).toHaveBeenCalledWith({
      conversationId: 'conversation-1',
      userMessageId: 'user-1',
      checkpointId: 'checkpoint-1',
    })
    expect(cs.state.value.messageId).toBe('assistant-1')
  })

  it('message_start replay 可再次通知下游，但不改变 assistant messageId', async () => {
    const onCheckpointAnchor = vi.fn()
    const cs = useChatStream({ onCheckpointAnchor })
    await cs.start(chatReq as never)
    const payload = {
      message_id: 'assistant-1',
      agent_id: 'a',
      conversation_id: 'conversation-1',
      task_id: 'task-1',
      user_message_id: 'user-1',
      checkpoint_id: 'checkpoint-1',
    }

    chatHandlers!.onEvent(ev('message_start', 1, payload))
    chatHandlers!.onEvent(ev('message_start', 1, payload))

    expect(onCheckpointAnchor).toHaveBeenCalledTimes(2)
    expect(cs.state.value.messageId).toBe('assistant-1')
  })

  it('旧 message_start 缺少任一锚点字段时保持兼容且不触发回调', async () => {
    const onCheckpointAnchor = vi.fn()
    const cs = useChatStream({ onCheckpointAnchor })
    await cs.start(chatReq as never)

    chatHandlers!.onEvent(ev('message_start', 1, {
      message_id: 'assistant-1',
      agent_id: 'a',
      conversation_id: 'conversation-1',
      task_id: 'task-1',
      user_message_id: 'user-1',
    }))

    expect(onCheckpointAnchor).not.toHaveBeenCalled()
    expect(cs.state.value.messageId).toBe('assistant-1')
    expect(cs.state.value.conversationId).toBe('conversation-1')
  })

  it('stopAll 会中止 shell 内所有会话流', () => {
    const signals: AbortSignal[] = []
    streamChat.mockImplementation((_url: unknown, _req: unknown, _h: SseHandlers, signal: AbortSignal) => {
      signals.push(signal)
      return new Promise<void>(() => {})
    })
    const cs = useChatStream()
    cs.setConversation('c_a')
    void cs.start({ ...chatReq, conversation_id: 'c_a' } as never)
    cs.setConversation('c_b')
    void cs.start({ ...chatReq, conversation_id: 'c_b' } as never)

    cs.stopAll()

    expect(signals).toHaveLength(2)
    expect(signals.every((signal) => signal.aborted)).toBe(true)
  })

  it('resetConversation 会清理状态并丢弃迟到的 token/tool/done 事件', async () => {
    const persisted = vi.fn()
    const cs = useChatStream({ onPersistedMessage: persisted })
    await cs.start({ ...chatReq, conversation_id: 'c_reset' } as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c_reset', task_id: 't1' }))
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'calculator', input: {}, require_confirm: false }))
    cs.resetConversation('c_reset')

    chatHandlers!.onEvent(ev('token', 3, { text: '迟到文本' }))
    chatHandlers!.onEvent(ev('tool_result', 4, { tool_call_id: 'tc1', tool_name: 'calculator', ok: true, summary: '迟到结果' }))
    chatHandlers!.onEvent(ev('done', 5, { message_id: 'm2', message: { id: 'm2' } }))
    flushNow()

    expect(cs.state.value.streaming).toBe(false)
    expect(cs.state.value.phase).toBe('idle')
    expect(cs.state.value.partialText).toBe('')
    expect(cs.state.value.segments).toEqual([])
    expect(cs.state.value.toolCalls).toEqual({})
    expect(persisted).not.toHaveBeenCalled()
  })

  it('reconcileTaskTerminal 只把 done/failed/cancelled 视为可继续回滚的终态', async () => {
    const cs = useChatStream()
    await cs.start({ ...chatReq, conversation_id: 'c_terminal' } as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', conversation_id: 'c_terminal', task_id: 't_terminal' }))

    getTaskStatus.mockResolvedValueOnce({ status: 'running' })
    expect(await cs.reconcileTaskTerminal('c_terminal')).toBe(false)
    getTaskStatus.mockResolvedValueOnce({ status: 'done' })
    expect(await cs.reconcileTaskTerminal('c_terminal')).toBe(true)
    expect(cs.state.value.phase).toBe('done')
  })

  it('token 流拼接 → partialText/segments 正确', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('token', 2, { text: '你好' }))
    chatHandlers!.onEvent(ev('token', 3, { text: '世界' }))
    flushNow()
    expect(cs.state.value.partialText).toBe('你好世界')
    expect(cs.state.value.segments).toHaveLength(1)
    expect(cs.state.value.taskId).toBe('t1')
  })

  it('message_start 不播种空文本段；tool_call 先于文本时文本段置顶', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    expect(cs.state.value.segments).toHaveLength(0)
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'web_search', input: {}, require_confirm: false }))
    chatHandlers!.onEvent(ev('token', 3, { text: '检索结果…' }))
    flushNow()
    expect(cs.state.value.segments).toHaveLength(2)
    expect(cs.state.value.segments[0]).toMatchObject({ kind: 'text', text: '检索结果…' })
    expect(cs.state.value.segments[1]).toMatchObject({ kind: 'tool', cardId: 'tc1' })
  })

  it('agent_switch → segments 追加 agent 段（from/to/reason）', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('agent_switch', 2, { from_agent: 'ag_proposer', to_agent: 'ag_reviewer', reason: '提案需审核' }))
    expect(cs.state.value.segments).toHaveLength(1)
    expect(cs.state.value.segments[0]).toMatchObject({
      kind: 'agent',
      from: 'ag_proposer',
      to: 'ag_reviewer',
      reason: '提案需审核',
    })
    expect(cs.state.value.streaming).toBe(true) // 切换事件不改变流式状态
  })

  it('thinking 累积到末段（连续事件不堆叠）；缺 text 兜底不崩', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('thinking', 2, { text: '正在推理…', ts: 1700000000000 }))
    chatHandlers!.onEvent(ev('thinking', 3, { text: '继续推理', ts: 1700000000000 }))
    expect(cs.state.value.segments).toHaveLength(1)
    expect(cs.state.value.segments[0]).toMatchObject({ kind: 'thinking', text: '正在推理…继续推理' })
    // 缺 text 兜底空串追加，不堆叠新段
    chatHandlers!.onEvent(ev('thinking', 4, { ts: 1700000000000 }))
    expect(cs.state.value.segments).toHaveLength(1)
    expect(cs.state.value.segments[0]).toMatchObject({ kind: 'thinking', text: '正在推理…继续推理' })
  })

  it('message 事件封口一轮：追加消息 + 复位段（保留 taskId）；done 追加最后一条', async () => {
    const persisted: unknown[] = []
    const cs = useChatStream({ onPersistedMessage: (m) => persisted.push(m) })
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('token', 2, { text: '检索中' }))
    chatHandlers!.onEvent(ev('message', 3, { message: { id: 'm1', conversation_id: 'c', role: 'assistant', content: '检索中', tool_calls: [], created_at: 'x' }, token_usage: { total_tokens: 180 }, cost: 0.0008 }))
    // 轮1 追加 + 段复位，但跨轮上下文保留
    expect(persisted).toHaveLength(1)
    expect(cs.state.value.segments).toHaveLength(0)
    expect(cs.state.value.partialText).toBe('')
    expect(cs.state.value.taskId).toBe('t1')
    expect(cs.state.value.conversationId).toBe('c')
    // 封口载荷的 token_usage/cost 透传到追加消息
    const sealed = persisted[0] as { token_usage?: { total_tokens: number }; cost?: number }
    expect(sealed.token_usage?.total_tokens).toBe(180)
    expect(sealed.cost).toBe(0.0008)
    // 下一轮 token + done 追加最后一条（done 顶层 token_usage/cost 兜底附到最终消息）
    chatHandlers!.onEvent(ev('token', 4, { text: '答案' }))
    chatHandlers!.onEvent(ev('done', 5, { message_id: 'm2', message: { id: 'm2', conversation_id: 'c', role: 'assistant', content: '答案', tool_calls: [], created_at: 'x' }, token_usage: { total_tokens: 84 }, cost: 0.0012 }))
    expect(persisted).toHaveLength(2)
    const final = persisted[1] as { token_usage?: { total_tokens: number }; cost?: number }
    expect(final.token_usage?.total_tokens).toBe(84)
    expect(final.cost).toBe(0.0012)
    expect(cs.state.value.finished).toBe(true)
  })

  it('message 封口：message 自带 token_usage/cost 时优先，不被载荷顶层覆盖', async () => {
    const persisted: unknown[] = []
    const cs = useChatStream({ onPersistedMessage: (m) => persisted.push(m) })
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('message', 3, { message: { id: 'm1', conversation_id: 'c', role: 'assistant', content: 'x', token_usage: { total_tokens: 999 }, cost: 0.0099, tool_calls: [], created_at: 'x' }, token_usage: { total_tokens: 180 }, cost: 0.0008 }))
    const sealed = persisted[0] as { token_usage?: { total_tokens: number }; cost?: number }
    expect(sealed.token_usage?.total_tokens).toBe(999)
    expect(sealed.cost).toBe(0.0099)
  })

  it('tool_call → 建卡；占位→回填 done', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'calculator', input: { expression: '6*7' }, require_confirm: false }))
    expect(cs.state.value.toolCalls.tc1.status).toBe('running')

    chatHandlers!.onEvent(ev('tool_result', 3, { tool_call_id: 'tc1', tool_name: 'calculator', ok: true, summary: '处理中…', placeholder: true, job_ref: 'job1' }))
    expect(cs.state.value.toolCalls.tc1.job_ref).toBe('job1')
    expect(cs.state.value.toolCalls.tc1.status).toBe('running')

    chatHandlers!.onEvent(ev('tool_result', 4, { tool_call_id: 'tc1', tool_name: 'calculator', ok: true, summary: '计算结果：42', structured: { result: 42 }, placeholder: false, job_ref: 'job1' }))
    expect(cs.state.value.toolCalls.tc1.status).toBe('done')
    expect(cs.state.value.toolCalls.tc1.summary).toBe('计算结果：42')
  })

  it('interrupt → confirmInterrupt(true) 续流 → done', async () => {
    const persisted = vi.fn()
    const cs = useChatStream({ onPersistedMessage: persisted })
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'calculator', input: {}, require_confirm: true }))
    expect(cs.state.value.toolCalls.tc1.status).toBe('awaiting_confirm')

    chatHandlers!.onEvent(ev('interrupt', 3, { node_id: 'node_tool', payload: {}, confirm_required: true, task_id: 't1' }))
    expect(cs.state.value.interrupted).not.toBeNull()
    expect(cs.state.value.status).toBe('waiting_confirm')
    expect(cs.state.value.streaming).toBe(false)

    await cs.confirmInterrupt(true)
    expect(streamTaskResume).toHaveBeenCalledWith('t1', expect.objectContaining({ approved: true }), expect.anything(), expect.anything())

    resumeHandlers!.onEvent(ev('token', 10, { text: '继续' }))
    resumeHandlers!.onEvent(ev('tool_result', 11, { tool_call_id: 'tc1', tool_name: 'calculator', ok: true, summary: '42', placeholder: false }))
    resumeHandlers!.onEvent(ev('done', 12, { message_id: 'm1', message: { id: 'msg_final' } }))
    flushNow()
    expect(cs.state.value.toolCalls.tc1.status).toBe('done')
    expect(cs.state.value.finished).toBe(true)
    expect(persisted).toHaveBeenCalledWith({ id: 'msg_final' })
  })

  it('confirmInterrupt(false) 走取消分支', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('interrupt', 2, { node_id: 'n', task_id: 't1' }))
    await cs.confirmInterrupt(false)
    expect(streamTaskResume).toHaveBeenCalledWith('t1', { approved: false }, expect.anything(), expect.anything())
  })

  it('error 事件 → state.error 置位 + finished', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c' }))
    chatHandlers!.onEvent(ev('error', 2, { code: 60001, message: 'LLM 调用失败', retryable: true }))
    expect(cs.state.value.error).toMatchObject({ code: 60001, retryable: true })
    expect(cs.state.value.finished).toBe(true)
  })

  it('stop() 先请求后端取消，再中止 SSE 并标记已中断', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('token', 2, { text: 'a' }))
    await cs.stop()
    expect(cancelTask).toHaveBeenCalledWith('t1')
    expect(cs.state.value.streaming).toBe(false)
    expect(cs.state.value.phase).toBe('cancelled')
    expect(cs.state.value.status).toBe('cancelled')
  })

  it('兼容旧后端：没有 task_id 时停止当前 SSE 并明确返回 unavailable', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c' }))
    chatHandlers!.onEvent(ev('token', 2, { text: '局部回复' }))
    const result = await cs.stop()
    expect(result).toBe('unavailable')
    expect(cs.state.value.phase).toBe('cancelled')
    expect(cs.state.value.streaming).toBe(false)
    expect(cancelTask).not.toHaveBeenCalled()
  })

  it('静默关流（无 done/error）→ streaming 复位（finally 兜底）', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never) // mock 立即 resolve、未发任何事件
    expect(cs.state.value.streaming).toBe(false)
  })

  it('缺少 task_id 且无 conversation_id 时 confirmInterrupt 报错而非崩溃', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: null }))
    chatHandlers!.onEvent(ev('interrupt', 2, { node_id: 'n' }))
    await cs.confirmInterrupt(true)
    expect(cs.state.value.error).toMatchObject({ code: 40001 })
    expect(streamTaskResume).not.toHaveBeenCalled()
  })

  it('approved resume 在 Promise/SSE 之前立即进入 resuming，并在 ack 后切换工具执行', async () => {
    const cs = useChatStream()
    await cs.start({ ...chatReq, conversation_id: 'c1' } as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c1', task_id: 't1' }))
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'shell', input: {}, require_confirm: true }))
    chatHandlers!.onEvent(ev('interrupt', 3, { node_id: 'n', task_id: 't1' }))
    streamTaskResume.mockImplementation((_id: unknown, _c: unknown, h: SseHandlers) => {
      resumeHandlers = h
      return new Promise<void>(() => {})
    })
    const pending = cs.confirmInterrupt(true)
    expect(cs.state.value.phase).toBe('resuming')
    expect(cs.state.value.phaseDetail).toBe('shell')
    expect(cs.state.value.confirming).toBe(true)
    expect(cs.state.value.interrupted).toBeNull()
    expect(cs.state.value.toolCalls.tc1.status).toBe('running')
    expect(cs.state.value.activities.some((a) => a.label.includes('已确认，正在继续执行 shell'))).toBe(true)
    resumeHandlers!.onEvent(ev('status', 4, { status: 'running', phase: 'tool', detail: 'shell', accepted: true, tool_call_id: 'tc1' }))
    expect(cs.state.value.phase).toBe('tool')
    expect(cs.state.value.confirming).toBe(false)
    expect(cs.state.value.phaseDetail).toBe('shell')
    await Promise.resolve()
    void pending
  })

  it('resume HTTP 错误恢复 waiting_confirm，仍可使用同一 task 重试', async () => {
    const cs = useChatStream()
    await cs.start({ ...chatReq, conversation_id: 'c1' } as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c1', task_id: 't1' }))
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'shell', input: {}, require_confirm: true }))
    chatHandlers!.onEvent(ev('interrupt', 3, { node_id: 'n', task_id: 't1' }))
    streamTaskResume.mockImplementation((_id: unknown, _c: unknown, h: SseHandlers) => { h.onError?.(new Error('拒绝')); return Promise.resolve() })
    await cs.confirmInterrupt(true)
    expect(cs.state.value.interrupted).not.toBeNull()
    expect(cs.state.value.phase).toBe('waiting_confirm')
    expect(cs.state.value.confirming).toBe(false)
  })

  it('多流：切换会话状态隔离，后台流继续写入各自 ctx，切回可见累积', async () => {
    const cs = useChatStream()
    await cs.start({ ...chatReq, conversation_id: 'cA' } as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'cA', task_id: 't1' }))
    chatHandlers!.onEvent(ev('token', 2, { text: 'A的内容' }))
    flushNow()
    expect(cs.state.value.partialText).toBe('A的内容')
    expect(cs.state.value.conversationId).toBe('cA')

    // 切到 B → state 指向 B 空态；A 的后台流事件写入 A 的 ctx，不污染 B
    cs.setConversation('cB')
    expect(cs.state.value.partialText).toBe('')
    chatHandlers!.onEvent(ev('token', 3, { text: '续写' }))
    flushNow()
    expect(cs.state.value.partialText).toBe('')

    // 切回 A → 切换前文本 + 后台续写可见（不 reset）
    cs.setConversation('cA')
    expect(cs.state.value.partialText).toBe('A的内容续写')
    expect(cs.state.value.streaming).toBe(true)
  })
})

describe('useChatStream 断线恢复（长任务契约）', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  async function startStream(cs: ReturnType<typeof useChatStream>, taskSeq = 1): Promise<void> {
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(evSeq('message_start', 1, taskSeq, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
  }

  it('断流（已有 task_id）→ reconnecting，不标记 failed、不重发原 chat；退避后按 cursor 订阅', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const cs = useChatStream()
    await startStream(cs)

    chatHandlers!.onError?.(transportError())

    expect(cs.state.value.phase).toBe('reconnecting')
    expect(cs.state.value.status).toBe('running')
    expect(cs.state.value.error).toBeNull()
    expect(cs.state.value.finished).toBe(false)
    expect(streamChat).toHaveBeenCalledTimes(1) // 不重发原 chat

    await vi.advanceTimersByTimeAsync(300)
    expect(streamTaskEvents).toHaveBeenCalledWith('t1', expect.objectContaining({ afterSeq: 1 }), expect.anything())
  })

  it('3 次退避耗尽 → 终局对账 → background_running；对账失败 → disconnected', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    getTaskStatus.mockResolvedValue({ status: 'running' } as never)
    const cs = useChatStream()
    await startStream(cs)

    chatHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(300)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(600)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(1200)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(0)

    expect(getTaskStatus).toHaveBeenCalledWith('t1')
    expect(cs.state.value.phase).toBe('background_running')
    expect(cs.state.value.streaming).toBe(false)
    expect(streamTaskEvents).toHaveBeenCalledTimes(3)

    // 对账本身失败 → disconnected
    getTaskStatus.mockRejectedValue(new Error('对账失败'))
    chatHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(300)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(600)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(1200)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(0)
    expect(cs.state.value.phase).toBe('disconnected')
  })

  it('对账 waiting_confirm → 恢复中断弹窗状态与确认卡', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    getTaskStatus.mockResolvedValue({ status: 'waiting_confirm', pending_confirm: { node_id: 'n1', reason: '需确认' } } as never)
    const cs = useChatStream()
    await startStream(cs)
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'shell', input: {}, require_confirm: true }))

    chatHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(300)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(600)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(1200)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(0)

    expect(cs.state.value.phase).toBe('waiting_confirm')
    expect(cs.state.value.interrupted).toMatchObject({ node_id: 'n1', task_id: 't1' })
    expect(cs.state.value.toolCalls.tc1.status).toBe('awaiting_confirm')
  })

  it('对账 done → onTaskSettled 通知视图层 reload', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    getTaskStatus.mockResolvedValue({ status: 'done' } as never)
    const onTaskSettled = vi.fn()
    const cs = useChatStream({ onTaskSettled })
    await startStream(cs)

    chatHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(300)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(600)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(1200)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(0)

    expect(cs.state.value.phase).toBe('done')
    expect(cs.state.value.finished).toBe(true)
    expect(onTaskSettled).toHaveBeenCalledWith({ taskId: 't1', conversationId: 'c', status: 'done' })
  })

  it('对账 failed+recoverable → recoverable 态；不可恢复 → failed', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    getTaskStatus.mockResolvedValue({ status: 'failed', error: { code: 60005, message: '模型连接中断', kind: 'llm_transport', recoverable: true } } as never)
    const cs = useChatStream()
    await startStream(cs)

    chatHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(300)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(600)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(1200)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(0)

    expect(cs.state.value.phase).toBe('recoverable')
    expect(cs.state.value.error).toMatchObject({ kind: 'llm_transport', recoverable: true })

    getTaskStatus.mockResolvedValue({ status: 'failed', error: { code: 60005, message: 'x', recoverable: false } } as never)
    chatHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(300)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(600)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(1200)
    eventsHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(0)
    expect(cs.state.value.phase).toBe('failed')
  })

  it('task_seq 跨连接去重：<= cursor 丢弃；token 无 task_seq 只当前连接消费不推进 cursor', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const cs = useChatStream()
    await startStream(cs) // cursor = 1

    chatHandlers!.onError?.(transportError())
    await vi.advanceTimersByTimeAsync(300)
    // 重连订阅：task_seq=2 应用并推进 cursor
    eventsHandlers!.onEvent(evSeq('tool_result', 1, 2, { tool_call_id: 'tc1', tool_name: 'web_search', ok: true, placeholder: false, summary: 'x' }))
    // 重复 task_seq=1 / =2 丢弃
    eventsHandlers!.onEvent(evSeq('token', 2, 1, { text: '重复1' }))
    eventsHandlers!.onEvent(evSeq('done', 3, 2, { message_id: 'm2', message: { id: 'm2' } }))
    expect(cs.state.value.finished).toBe(false)
    // token 无 task_seq：当前连接消费
    eventsHandlers!.onEvent(ev('token', 4, { text: '增量' }))
    flushNow()
    expect(cs.state.value.partialText).toBe('增量')
    // cursor 未被 token 污染：task_seq=3 仍可应用
    eventsHandlers!.onEvent(evSeq('done', 5, 3, { message_id: 'm2', message: { id: 'm2' } }))
    expect(cs.state.value.finished).toBe(true)
    expect(cs.state.value.phase).toBe('done')
  })

  it('model_retry(reset_partial=true) 只清未封口文本/thinking，保留工具卡，随后业务帧恢复', async () => {
    const cs = useChatStream()
    await startStream(cs)
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'web_search', input: {}, require_confirm: false }))
    chatHandlers!.onEvent(ev('thinking', 3, { text: '推理中…', ts: 1 }))
    chatHandlers!.onEvent(ev('token', 4, { text: '部分输出' }))
    flushNow()
    expect(cs.state.value.partialText).toBe('部分输出')

    chatHandlers!.onEvent(ev('model_retry', 5, { attempt: 1, max_attempts: 1, reset_partial: true, reason: 'llm_transport', message: '模型连接中断，正从最近断点重试' }))
    expect(cs.state.value.partialText).toBe('')
    expect(cs.state.value.segments).toHaveLength(1) // 仅 tool 段
    expect(cs.state.value.segments[0]).toMatchObject({ kind: 'tool', cardId: 'tc1' })
    expect(cs.state.value.phase).toBe('retrying')
    expect(cs.state.value.phaseDetail).toBe('（1/1）')
    expect(cs.state.value.streaming).toBe(true)

    chatHandlers!.onEvent(ev('token', 6, { text: '恢复后的输出' }))
    expect(cs.state.value.phase).toBe('responding')
  })

  it('error 事件 recoverable=true 直接进 recoverable 态（非 failed）', async () => {
    const cs = useChatStream()
    await startStream(cs)
    chatHandlers!.onEvent(ev('error', 2, { code: 60005, message: '模型连接中断', kind: 'llm_transport', retryable: true, recoverable: true }))
    expect(cs.state.value.phase).toBe('recoverable')
    expect(cs.state.value.error).toMatchObject({ code: 60005, recoverable: true })
  })

  it('recover 链路：调用 recoverTask → 立即订阅 events；失败回 recoverable；防双击', async () => {
    const cs = useChatStream()
    await startStream(cs)
    chatHandlers!.onEvent(ev('error', 2, { code: 60005, message: 'x', recoverable: true }))
    expect(cs.state.value.phase).toBe('recoverable')

    await cs.recover()
    // 幂等 key 由 task-control.recoverTask 默认参数生成（task-control.spec 覆盖），此处只验证任务 id 与调用链
    expect(recoverTask.mock.calls[0][0]).toBe('t1')
    expect(cs.state.value.phase).toBe('reconnecting')
    expect(streamTaskEvents).toHaveBeenCalledTimes(1)

    // 失败回位
    recoverTask.mockRejectedValue(new Error('40903 恢复被拒'))
    chatHandlers!.onEvent(ev('error', 3, { code: 60005, message: 'x', recoverable: true }))
    await cs.recover()
    expect(cs.state.value.phase).toBe('recoverable')
    expect(cs.state.value.error).not.toBeNull()

    // 防双击：recover 在途时重复调用只发一次
    let resolveRecover!: (v: unknown) => void
    recoverTask.mockClear()
    recoverTask.mockImplementation(() => new Promise((res) => { resolveRecover = res }))
    chatHandlers!.onEvent(ev('error', 4, { code: 60005, message: 'x', recoverable: true }))
    const p1 = cs.recover()
    const p2 = cs.recover()
    expect(recoverTask).toHaveBeenCalledTimes(1)
    resolveRecover({ task_id: 't1', status: 'running' })
    await p1
    await p2
  })

  it('重连期 stop：真实取消任务并清理重连定时器', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const cs = useChatStream()
    await startStream(cs)

    chatHandlers!.onError?.(transportError())
    expect(cs.state.value.phase).toBe('reconnecting')
    await cs.stop()
    expect(cancelTask).toHaveBeenCalledWith('t1')
    expect(cs.state.value.phase).toBe('cancelled')
    await vi.advanceTimersByTimeAsync(5000)
    expect(streamTaskEvents).not.toHaveBeenCalled()
  })

  it('stopAll 清理所有会话的重连定时器', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const cs = useChatStream()
    await cs.start({ ...chatReq, conversation_id: 'cA' } as never)
    chatHandlers!.onEvent(evSeq('message_start', 1, 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'cA', task_id: 't1' }))
    chatHandlers!.onError?.(transportError())
    await cs.start({ ...chatReq, conversation_id: 'cB' } as never)
    chatHandlers!.onEvent(evSeq('message_start', 1, 1, { message_id: 'm2', agent_id: 'a', conversation_id: 'cB', task_id: 't2' }))
    chatHandlers!.onError?.(transportError())

    cs.stopAll()
    await vi.advanceTimersByTimeAsync(5000)
    expect(streamTaskEvents).not.toHaveBeenCalled()
  })

  it('旧后端：断线但无 task_id → 保持既有 failed 语义', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c' }))
    chatHandlers!.onError?.(transportError())
    expect(cs.state.value.phase).toBe('failed')
    expect(cs.state.value.error).toMatchObject({ code: 50001, retryable: true })
    expect(streamTaskEvents).not.toHaveBeenCalled()
  })

  it('chat 流 EOF 无 done（半截 body）→ 进入重连链', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const cs = useChatStream()
    await startStream(cs)
    chatHandlers!.onClose?.({ hadEvents: true, lastSeq: 1, lastTaskSeq: 1 })
    expect(cs.state.value.phase).toBe('reconnecting')
    expect(cs.state.value.streaming).toBe(true)
    await vi.advanceTimersByTimeAsync(300)
    expect(streamTaskEvents).toHaveBeenCalledTimes(1)
  })

  it('resume 断线对账 running → 升级为 events 订阅', async () => {
    getTaskStatus.mockResolvedValue({ status: 'running' } as never)
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'shell', input: {}, require_confirm: true }))
    chatHandlers!.onEvent(ev('interrupt', 3, { node_id: 'n', task_id: 't1' }))
    streamTaskResume.mockImplementation((_id: unknown, _c: unknown, h: SseHandlers) => {
      h.onError?.(transportError())
      return Promise.resolve()
    })
    await cs.confirmInterrupt(true)
    expect(cs.state.value.phase).toBe('reconnecting')
    expect(streamTaskEvents).toHaveBeenCalled()
  })
})
