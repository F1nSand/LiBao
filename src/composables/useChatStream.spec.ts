import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushNow } from '@/utils/rAF'
import type { SseEnvelope } from '@/types'
import type { SseHandlers } from '@/api/sse'

const { streamChat, streamTaskResume } = vi.hoisted(() => ({
  streamChat: vi.fn(),
  streamTaskResume: vi.fn(),
}))

vi.mock('@/api/sse', () => ({
  streamChat,
  streamChatAt: streamChat,
  streamTaskResume,
}))

import { useChatStream } from './useChatStream'

let chatHandlers: SseHandlers | null = null
let resumeHandlers: SseHandlers | null = null

function ev(type: string, seq: number, payload: unknown): SseEnvelope {
  return { id: `e${seq}`, seq, type: type as SseEnvelope['type'], ts: 1700000000000, payload }
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
  streamChat.mockImplementation((_url: unknown, _req: unknown, h: SseHandlers) => {
    chatHandlers = h
    return Promise.resolve()
  })
  streamTaskResume.mockImplementation((_id: unknown, _c: unknown, h: SseHandlers) => {
    resumeHandlers = h
    return Promise.resolve()
  })
})

describe('useChatStream 状态机', () => {
  it('token 流拼接 → partialText/segments 正确', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('token', 2, { text: '你好' }))
    chatHandlers!.onEvent(ev('token', 3, { text: '世界' }))
    flushNow()
    expect(cs.state.partialText).toBe('你好世界')
    expect(cs.state.segments).toHaveLength(1)
    expect(cs.state.taskId).toBe('t1')
  })

  it('message_start 不播种空文本段；tool_call 先于文本时文本段置顶', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    expect(cs.state.segments).toHaveLength(0)
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'web_search', input: {}, require_confirm: false }))
    chatHandlers!.onEvent(ev('token', 3, { text: '检索结果…' }))
    flushNow()
    expect(cs.state.segments).toHaveLength(2)
    expect(cs.state.segments[0]).toMatchObject({ kind: 'text', text: '检索结果…' })
    expect(cs.state.segments[1]).toMatchObject({ kind: 'tool', cardId: 'tc1' })
  })

  it('agent_switch → segments 追加 agent 段（from/to/reason）', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('agent_switch', 2, { from_agent: 'ag_proposer', to_agent: 'ag_reviewer', reason: '提案需审核' }))
    expect(cs.state.segments).toHaveLength(1)
    expect(cs.state.segments[0]).toMatchObject({
      kind: 'agent',
      from: 'ag_proposer',
      to: 'ag_reviewer',
      reason: '提案需审核',
    })
    expect(cs.state.streaming).toBe(true) // 切换事件不改变流式状态
  })

  it('thinking 累积到末段（连续事件不堆叠）；缺 text 兜底不崩', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('thinking', 2, { text: '正在推理…', ts: 1700000000000 }))
    chatHandlers!.onEvent(ev('thinking', 3, { text: '继续推理', ts: 1700000000000 }))
    expect(cs.state.segments).toHaveLength(1)
    expect(cs.state.segments[0]).toMatchObject({ kind: 'thinking', text: '正在推理…继续推理' })
    // 缺 text 兜底空串追加，不堆叠新段
    chatHandlers!.onEvent(ev('thinking', 4, { ts: 1700000000000 }))
    expect(cs.state.segments).toHaveLength(1)
    expect(cs.state.segments[0]).toMatchObject({ kind: 'thinking', text: '正在推理…继续推理' })
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
    expect(cs.state.segments).toHaveLength(0)
    expect(cs.state.partialText).toBe('')
    expect(cs.state.taskId).toBe('t1')
    expect(cs.state.conversationId).toBe('c')
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
    expect(cs.state.finished).toBe(true)
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
    expect(cs.state.toolCalls.tc1.status).toBe('running')

    chatHandlers!.onEvent(ev('tool_result', 3, { tool_call_id: 'tc1', tool_name: 'calculator', ok: true, summary: '处理中…', placeholder: true, job_ref: 'job1' }))
    expect(cs.state.toolCalls.tc1.job_ref).toBe('job1')
    expect(cs.state.toolCalls.tc1.status).toBe('running')

    chatHandlers!.onEvent(ev('tool_result', 4, { tool_call_id: 'tc1', tool_name: 'calculator', ok: true, summary: '计算结果：42', structured: { result: 42 }, placeholder: false, job_ref: 'job1' }))
    expect(cs.state.toolCalls.tc1.status).toBe('done')
    expect(cs.state.toolCalls.tc1.summary).toBe('计算结果：42')
  })

  it('interrupt → confirmInterrupt(true) 续流 → done', async () => {
    const persisted = vi.fn()
    const cs = useChatStream({ onPersistedMessage: persisted })
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c', task_id: 't1' }))
    chatHandlers!.onEvent(ev('tool_call', 2, { tool_call_id: 'tc1', tool_name: 'calculator', input: {}, require_confirm: true }))
    expect(cs.state.toolCalls.tc1.status).toBe('awaiting_confirm')

    chatHandlers!.onEvent(ev('interrupt', 3, { node_id: 'node_tool', payload: {}, confirm_required: true, task_id: 't1' }))
    expect(cs.state.interrupted).not.toBeNull()
    expect(cs.state.status).toBe('waiting_confirm')
    expect(cs.state.streaming).toBe(false)

    await cs.confirmInterrupt(true)
    expect(streamTaskResume).toHaveBeenCalledWith('t1', expect.objectContaining({ approved: true }), expect.anything(), expect.anything())

    resumeHandlers!.onEvent(ev('token', 10, { text: '继续' }))
    resumeHandlers!.onEvent(ev('tool_result', 11, { tool_call_id: 'tc1', tool_name: 'calculator', ok: true, summary: '42', placeholder: false }))
    resumeHandlers!.onEvent(ev('done', 12, { message_id: 'm1', message: { id: 'msg_final' } }))
    flushNow()
    expect(cs.state.toolCalls.tc1.status).toBe('done')
    expect(cs.state.finished).toBe(true)
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
    expect(cs.state.error).toMatchObject({ code: 60001, retryable: true })
    expect(cs.state.finished).toBe(true)
  })

  it('stop() abort 并置 streaming=false', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: 'c' }))
    chatHandlers!.onEvent(ev('token', 2, { text: 'a' }))
    cs.stop()
    expect(cs.state.streaming).toBe(false)
  })

  it('静默关流（无 done/error）→ streaming 复位（finally 兜底）', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never) // mock 立即 resolve、未发任何事件
    expect(cs.state.streaming).toBe(false)
  })

  it('缺少 task_id 且无 conversation_id 时 confirmInterrupt 报错而非崩溃', async () => {
    const cs = useChatStream()
    await cs.start(chatReq as never)
    chatHandlers!.onEvent(ev('message_start', 1, { message_id: 'm1', agent_id: 'a', conversation_id: null }))
    chatHandlers!.onEvent(ev('interrupt', 2, { node_id: 'n' }))
    await cs.confirmInterrupt(true)
    expect(cs.state.error).toMatchObject({ code: 40001 })
    expect(streamTaskResume).not.toHaveBeenCalled()
  })
})
