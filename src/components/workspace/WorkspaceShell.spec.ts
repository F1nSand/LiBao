import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import type { Message, Paged } from '@/types'

const { listConversations, listMessages, streamState, setConversation, stop } = vi.hoisted(() => ({
  listConversations: vi.fn(),
  listMessages: vi.fn(),
  streamState: { value: { streaming: false, interrupted: null, error: null, status: 'idle', messageId: null, partialText: '' } },
  setConversation: vi.fn(),
  stop: vi.fn(),
}))

vi.mock('@/api/chat', () => ({
  listConversations,
  createConversation: vi.fn(),
  listMessages,
  deleteConversation: vi.fn(),
}))
vi.mock('@/composables/useChatStream', () => ({
  useChatStream: vi.fn(() => ({
    state: streamState,
    setConversation,
    start: vi.fn(),
    stop,
    confirmInterrupt: vi.fn(),
  })),
}))
vi.mock('@/composables/useMediaQuery', () => ({
  useMediaQuery: () => ref(false),
}))

import WorkspaceShell from './WorkspaceShell.vue'

function message(conversationId: string, content: string): Message {
  return {
    id: `${conversationId}-${content}`,
    conversation_id: conversationId,
    role: 'assistant',
    content,
    tool_calls: [],
    created_at: '2026-08-28T00:00:00.000Z',
  }
}

function page(conversationId: string, content: string): Paged<Message> {
  return { items: [message(conversationId, content)], total: 1, page: 1, page_size: 100 }
}

function mountShell() {
  return mount(WorkspaceShell, {
    props: { workspaceId: 'ws_001' },
    global: {
      stubs: {
        ResourceManager: true,
        TrajectoryPanel: true,
        AttachmentUploader: true,
        InterruptConfirmDialog: true,
        StatusTag: true,
        WorkspaceFileRefPicker: true,
        WorkspaceConvList: {
          props: ['items', 'activeId'],
          template: `<div data-testid="conversation-list">
            <button v-for="item in items" :key="item.id" :class="{ active: item.id === activeId }" :data-conversation-id="item.id" @click="$emit('select', item.id)">{{ item.title }}</button>
          </div>`,
        },
        MessageList: {
          props: ['messages', 'loading'],
          template: '<div data-testid="messages" :data-loading="loading">{{ messages.map((item) => item.content).join("|") }}</div>',
        },
        'el-radio-group': true,
        'el-radio-button': true,
        'el-button': true,
        'el-icon': true,
        'el-input': true,
        'el-empty': true,
      },
    },
  })
}

describe('WorkspaceShell conversation loading races', () => {
  beforeEach(() => {
    listConversations.mockReset()
    listMessages.mockReset()
    setConversation.mockReset()
    stop.mockReset()
    streamState.value = { streaming: false, interrupted: null, error: null, status: 'idle', messageId: null, partialText: '' }
    listConversations.mockResolvedValue({
      items: [
        { id: 'c_a', title: 'A' },
        { id: 'c_b', title: 'B' },
      ],
      total: 2,
      page: 1,
      page_size: 100,
    })
  })

  it('A→B→A 时只接受最后一次请求的结果', async () => {
    const requests: Array<{ resolve: (value: Paged<Message>) => void; reject: (error: Error) => void }> = []
    listMessages.mockImplementation(
      () =>
        new Promise<Paged<Message>>((resolve, reject) => {
          requests.push({ resolve, reject })
        }),
    )
    const wrapper = mountShell()
    await flushPromises()
    const buttons = wrapper.findAll('[data-conversation-id]')

    const firstA = buttons[0].trigger('click')
    const b = buttons[1].trigger('click')
    const secondA = buttons[0].trigger('click')
    await flushPromises()

    requests[0].resolve(page('c_a', '旧 A'))
    await firstA
    await flushPromises()
    expect(wrapper.get('[data-testid="messages"]').text()).toBe('')
    expect(wrapper.get('[data-testid="messages"]').attributes('data-loading')).toBe('true')

    requests[1].resolve(page('c_b', '旧 B'))
    await b
    await flushPromises()
    expect(wrapper.get('[data-testid="messages"]').text()).toBe('')
    expect(wrapper.get('[data-testid="messages"]').attributes('data-loading')).toBe('true')

    requests[2].resolve(page('c_a', '最新 A'))
    await secondA
    await flushPromises()
    expect(wrapper.get('[data-testid="messages"]').text()).toBe('最新 A')
    expect(wrapper.get('[data-testid="messages"]').attributes('data-loading')).toBe('false')
  })

  it('过期请求失败时不显示旧错误', async () => {
    const requests: Array<{ resolve: (value: Paged<Message>) => void; reject: (error: Error) => void }> = []
    listMessages.mockImplementation(
      () =>
        new Promise<Paged<Message>>((resolve, reject) => {
          requests.push({ resolve, reject })
        }),
    )
    const wrapper = mountShell()
    await flushPromises()
    const buttons = wrapper.findAll('[data-conversation-id]')
    const first = buttons[0].trigger('click')
    const latest = buttons[1].trigger('click')
    await flushPromises()

    requests[0].reject(new Error('A 失败'))
    await first
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="messages"]').attributes('data-loading')).toBe('true')

    requests[1].resolve(page('c_b', 'B 成功'))
    await latest
    await flushPromises()
    expect(wrapper.get('[data-testid="messages"]').text()).toBe('B 成功')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
