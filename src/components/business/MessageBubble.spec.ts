import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageBubble from './MessageBubble.vue'
import type { Message } from '@/types'
import type { StreamState } from '@/composables/useChatStream'

const asstMsg: Message = {
  id: 'm1',
  conversation_id: 'c1',
  role: 'assistant',
  content: '**答案**',
  tool_calls: [{ tool_call_id: 'tc1', tool_name: 'web_search', input: { q: 'x' }, status: 'done', position: 0 }],
  created_at: '2026-01-01T00:00:00Z',
}

const streamState: StreamState = {
  taskId: null,
  messageId: null,
  conversationId: null,
  segments: [
    { kind: 'tool', id: 's1', cardId: 'tc1' },
    { kind: 'text', id: 's2', text: '**答案**' },
  ],
  partialText: '**答案**',
  toolCalls: {
    tc1: { tool_call_id: 'tc1', tool_name: 'web_search', input: {}, status: 'done', startedAt: 0 },
  },
  status: 'done',
  interrupted: null,
  error: null,
  finished: true,
  streaming: false,
}

describe('MessageBubble 活动区 + 回复气泡（docs/02 §5.4.3）', () => {
  it('持久化助手消息：工具调用进活动区、文本进回复气泡、活动区在气泡上方', () => {
    const w = mount(MessageBubble, { props: { message: asstMsg } })
    const activity = w.find('.msg-activity')
    const text = w.find('.msg-text')
    expect(activity.exists()).toBe(true)
    expect(activity.text()).toContain('web_search')
    expect(text.exists()).toBe(true)
    expect(w.find('.markdown-body').text()).toContain('答案')
    // 活动区在回复气泡之前（DOM 顺序比较；html() 字符串 indexOf 会被模板注释干扰）
    expect(activity.element.compareDocumentPosition(text.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('流式消息：工具与文本分到活动区与回复气泡', () => {
    const w = mount(MessageBubble, { props: { stream: streamState } })
    expect(w.find('.msg-activity').text()).toContain('web_search')
    expect(w.find('.markdown-body').text()).toContain('答案')
  })

  it('用户消息仅文本气泡，无活动区', () => {
    const userMsg: Message = {
      id: 'u1',
      conversation_id: 'c1',
      role: 'user',
      content: '你好',
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: userMsg } })
    expect(w.find('.msg-activity').exists()).toBe(false)
    expect(w.find('.user-text').text()).toBe('你好')
  })

  it('工具轮无文本（content 空但有 tool_calls）→ 气泡占位「调用 [工具]：入参」', () => {
    const toolMsg: Message = {
      id: 'm2',
      conversation_id: 'c1',
      role: 'assistant',
      content: '',
      tool_calls: [
        { tool_call_id: 'tc1', tool_name: 'calculator', input: { expression: '(3+4)*2-1' }, status: 'done', position: 0 },
      ],
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: toolMsg } })
    expect(w.find('.msg-text').text()).toContain('调用 calculator：(3+4)*2-1')
    expect(w.find('.msg-activity .tool-card').exists()).toBe(true)
  })
})
