import { afterEach, describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const { messageError, messageSuccess } = vi.hoisted(() => ({
  messageError: vi.fn(),
  messageSuccess: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: messageError, success: messageSuccess },
}))

import MessageBubble from './MessageBubble.vue'
import type { Message } from '@/types'
import type { StreamState } from '@/composables/useChatStream'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

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
  phase: 'done',
  phaseDetail: null,
  cancelling: false,
  confirming: false,
  activities: [],
  interrupted: null,
  error: null,
  finished: true,
  streaming: false,
}

describe('MessageBubble 活动区 + 回复气泡（《02》前端设计 §5.4.3）', () => {
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

  it('带 checkpoint 的用户消息显示回滚入口并发出消息事件', async () => {
    const userMsg: Message = {
      id: 'u-checkpoint',
      conversation_id: 'c1',
      role: 'user',
      content: '修改文件',
      checkpoint_id: 'cp-1',
      checkpoint: { id: 'cp-1', status: 'sealed', changed_file_count: 1, can_restore_code: true, can_restore_conversation: true },
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: userMsg } })
    await w.get('[aria-label="回滚到此状态"]').trigger('click')
    expect(w.emitted('rollback')?.[0]).toEqual([userMsg])
  })

  it('带 checkpoint 的用户消息只显示回滚和复制图标，顺序固定且无可见长文案', () => {
    const userMsg: Message = {
      id: 'u-actions',
      conversation_id: 'c1',
      role: 'user',
      content: '修改文件',
      checkpoint_id: 'cp-1',
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: userMsg } })
    const buttons = w.findAll('.message-action')

    expect(buttons).toHaveLength(2)
    expect(buttons[0].attributes('aria-label')).toBe('回滚到此状态')
    expect(buttons[1].attributes('aria-label')).toBe('复制消息')
    expect(w.text()).not.toContain('回滚到此状态')
  })

  it('持久化助手正文只显示复制，流式消息不显示复制', () => {
    const assistant = mount(MessageBubble, { props: { message: asstMsg } })
    expect(assistant.findAll('.message-action')).toHaveLength(1)
    expect(assistant.find('[aria-label="回滚到此状态"]').exists()).toBe(false)

    const streaming = mount(MessageBubble, { props: { stream: streamState } })
    expect(streaming.find('.message-action').exists()).toBe(false)
  })

  it('纯附件用户消息有 checkpoint 时只显示回滚，不显示复制', () => {
    const userMsg: Message = {
      id: 'u-file',
      conversation_id: 'c1',
      role: 'user',
      content: '',
      attachments: [{ attachment_id: 'atc-1', name: 'report.pdf' }],
      checkpoint_id: 'cp-1',
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: userMsg } })
    expect(w.findAll('.message-action')).toHaveLength(1)
    expect(w.find('[aria-label="回滚到此状态"]').exists()).toBe(true)
    expect(w.find('[aria-label="复制消息"]').exists()).toBe(false)
  })

  it('复制成功时传入完整原始正文并显示成功反馈', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const w = mount(MessageBubble, { props: { message: asstMsg } })

    await w.get('[aria-label="复制消息"]').trigger('click')

    expect(writeText).toHaveBeenCalledWith('**答案**')
    expect(messageSuccess).toHaveBeenCalledWith('消息已复制')
  })

  it('复制失败时显示错误反馈且不抛出未处理 promise', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('clipboard denied'))
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const w = mount(MessageBubble, { props: { message: asstMsg } })

    await expect(w.get('[aria-label="复制消息"]').trigger('click')).resolves.toBeUndefined()

    expect(messageError).toHaveBeenCalledWith('复制失败，请重试')
  })

  it('消息操作图标具有对应 title 和 aria-label', () => {
    const userMsg: Message = {
      id: 'u-a11y',
      conversation_id: 'c1',
      role: 'user',
      content: '请修改',
      checkpoint_id: 'cp-1',
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: userMsg } })

    expect(w.get('[aria-label="回滚到此状态"]').attributes('title')).toBe('回滚到此状态')
    expect(w.get('[aria-label="复制消息"]').attributes('title')).toBe('复制消息')
  })

  it('操作栏使用稳定 class，不保留旧文字回滚入口', () => {
    const w = mount(MessageBubble, {
      props: {
        message: {
          id: 'u-stable-actions',
          conversation_id: 'c1',
          role: 'user',
          content: '请修改',
          checkpoint_id: 'cp-1',
          created_at: '2026-01-01T00:00:00Z',
        },
      },
    })

    expect(w.find('.message-actions').exists()).toBe(true)
    expect(w.find('.message-action.rollback-action').exists()).toBe(true)
    expect(w.find('.message-action.copy-action').exists()).toBe(true)
    expect(w.find('.rollback-trigger').exists()).toBe(false)
  })

  it('纯附件/纯引用消息不渲染空的用户文字气泡', () => {
    const userMsg: Message = {
      id: 'u-attachment',
      conversation_id: 'c1',
      role: 'user',
      content: '',
      attachments: [{ attachment_id: 'atc-1', name: 'report.pdf', mime_type: 'application/pdf', size: 2048, status: 'uploaded' }],
      file_refs: [{ path: 'docs/readme.md' }],
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: userMsg } })
    expect(w.find('.user-text').exists()).toBe(false)
    expect(w.find('.attach-file').exists()).toBe(true)
    expect(w.find('.file-ref-chip').exists()).toBe(true)
  })

  it('仅空白正文也不渲染文字气泡', () => {
    const w = mount(MessageBubble, {
      props: {
        message: {
          id: 'u-whitespace',
          conversation_id: 'c1',
          role: 'user',
          content: '  \n  ',
          created_at: '2026-01-01T00:00:00Z',
        },
      },
    })
    expect(w.find('.user-text').exists()).toBe(false)
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
    expect(w.find('.msg-activity .tool-row').exists()).toBe(true)
  })

  it('工具行：收起预览 `工具 · 摘要`，整行点击展开入参/输出/耗时', async () => {
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
    const row = w.find('.msg-activity .tool-row')
    expect(row.exists()).toBe(true)
    expect(row.find('.tool-row-head').element.tagName).toBe('BUTTON')
    expect(row.find('.tool-row-head').attributes('aria-expanded')).toBe('false')
    // 默认收起：只显示单行预览（工具 · 摘要），无 .tool-params
    expect(row.find('.tool-summary').text()).toContain('web_search · SSE')
    expect(row.find('.tool-params').exists()).toBe(false)
    // 整行点击展开 → 入参 + 输出 + 耗时可见
    await row.find('.tool-row-head').trigger('click')
    expect(row.find('.tool-params').exists()).toBe(true)
    expect(row.find('.tool-params').text()).toContain('入参')
    expect(row.find('.tool-params').text()).toContain('输出')
    expect(row.find('.tool-params').text()).toContain('812ms')
  })

  it('工具行：无入参/输出时点击不展开详情', async () => {
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
    expect(w.find('.tool-params').exists()).toBe(false)
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

  it('thinking：默认收起显示 `Think · 首行` 预览，整行点击展开全文', async () => {
    const msg: Message = {
      id: 'm6',
      conversation_id: 'c1',
      role: 'assistant',
      content: '答案',
      thinking: '这是一段足够长的推理内容，用于触发折叠显示的测试文本。'.repeat(6),
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: msg } })
    expect(w.find('.thinking-row').exists()).toBe(true)
    expect(w.find('.thinking-row').element.tagName).toBe('BUTTON')
    expect(w.find('.thinking-row').attributes('aria-expanded')).toBe('false')
    // 默认收起：单行预览 `Think · 首行截断`，不显示全文
    const preview = w.find('.thinking-preview')
    expect(preview.exists()).toBe(true)
    expect(preview.text()).toMatch(/^Think · /)
    expect(preview.text()).toContain('这是一段足够长的推理内容')
    expect(w.find('.thinking-text').exists()).toBe(false)
    // 整行点击展开 → 全文显示
    await w.find('.thinking-row').trigger('click')
    expect(w.find('.thinking-preview').exists()).toBe(false)
    expect(w.find('.thinking-text').exists()).toBe(true)
    expect(w.find('.thinking-text').text()).toContain('测试文本')
    // 再点收起 → 恢复预览
    await w.find('.thinking-row').trigger('click')
    expect(w.find('.thinking-preview').exists()).toBe(true)
    expect(w.find('.thinking-text').exists()).toBe(false)
  })

  it('thinking 短文本：同样默认收起（`Think · 简短推理`），整行点击展开', async () => {
    const msg: Message = {
      id: 'm7',
      conversation_id: 'c1',
      role: 'assistant',
      content: '答案',
      thinking: '简短推理',
      created_at: '2026-01-01T00:00:00Z',
    }
    const w = mount(MessageBubble, { props: { message: msg } })
    expect(w.find('.thinking-preview').text()).toBe('Think · 简短推理')
    expect(w.find('.thinking-text').exists()).toBe(false)
    await w.find('.thinking-row').trigger('click')
    expect(w.find('.thinking-text').text()).toBe('简短推理')
  })
})
