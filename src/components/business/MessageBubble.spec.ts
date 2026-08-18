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

  it('工具卡：入参/输出/耗时透传，「参数」展开可回放', async () => {
    const toolMsg: Message = {
      id: 'm3',
      conversation_id: 'c1',
      role: 'assistant',
      content: '已检索',
      tool_calls: [
        {
          tool_call_id: 'tc1',
          tool_name: 'web_search',
          input: { query: 'SSE' },
          output: { hits: 3 },
          status: 'done',
          position: 0,
          duration_ms: 812,
        },
      ],
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: toolMsg } })
    const card = w.find('.msg-activity .tool-card')
    expect(card.exists()).toBe(true)
    // 默认收起：无 .tool-params
    expect(card.find('.tool-params').exists()).toBe(false)
    expect(card.find('.tool-toggle').text()).toContain('参数')
    // 点击展开 → 入参 + 输出 + 耗时可见
    await card.find('.tool-toggle').trigger('click')
    expect(card.find('.tool-params').exists()).toBe(true)
    expect(card.find('.tool-params').text()).toContain('入参')
    expect(card.find('.tool-params').text()).toContain('输出')
    expect(card.find('.tool-params').text()).toContain('812ms')
  })

  it('工具卡：无入参/输出时不显示「参数」toggle', () => {
    const noParamsMsg: Message = {
      id: 'm5',
      conversation_id: 'c1',
      role: 'assistant',
      content: '已执行',
      tool_calls: [
        { tool_call_id: 'tc1', tool_name: 'some_tool', input: undefined, output: undefined, status: 'done', position: 0 },
      ],
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: noParamsMsg } })
    expect(w.find('.tool-toggle').exists()).toBe(false)
  })

  it('逐轮 token_usage/cost → 回复气泡下方 usage footer', () => {
    const msg: Message = {
      id: 'm4',
      conversation_id: 'c1',
      role: 'assistant',
      content: '答案',
      token_usage: { prompt_tokens: 120, completion_tokens: 60, total_tokens: 180 },
      cost: 0.0008,
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: msg } })
    const usage = w.find('.msg-usage')
    expect(usage.exists()).toBe(true)
    expect(usage.text()).toContain('180 tok')
    expect(usage.text()).toContain('¥0.0008')
  })

  it('无 token_usage/cost 时不渲染 usage footer', () => {
    const w = mount(MessageBubble, { props: { message: asstMsg } })
    expect(w.find('.msg-usage').exists()).toBe(false)
  })

  it('thinking 长文本：折叠行 + 展开/收起按钮，点击切换展开态', async () => {
    const msg: Message = {
      id: 'm6',
      conversation_id: 'c1',
      role: 'assistant',
      content: '答案',
      thinking: '这是一段足够长的推理内容，用于触发折叠显示的测试文本。'.repeat(6),
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: msg } })
    const row = w.find('.thinking-row')
    expect(row.exists()).toBe(true)
    const text = w.find('.thinking-text')
    expect(text.classes()).toContain('collapsed')
    const toggle = w.find('.thinking-toggle')
    expect(toggle.exists()).toBe(true)
    expect(toggle.text()).toBe('展开')
    // 点击展开 → 文本不再折叠、按钮变收起
    await toggle.trigger('click')
    expect(text.classes()).not.toContain('collapsed')
    expect(w.find('.thinking-toggle').text()).toBe('收起')
    // 再点收起 → 恢复折叠
    await w.find('.thinking-toggle').trigger('click')
    expect(text.classes()).toContain('collapsed')
  })

  it('thinking 短文本：无展开按钮、不折叠', () => {
    const msg: Message = {
      id: 'm7',
      conversation_id: 'c1',
      role: 'assistant',
      content: '答案',
      thinking: '简短推理',
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: msg } })
    expect(w.find('.thinking-toggle').exists()).toBe(false)
    expect(w.find('.thinking-text').classes()).not.toContain('collapsed')
  })
})
