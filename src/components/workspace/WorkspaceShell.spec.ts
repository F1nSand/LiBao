import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import type { FileRef, Message, Paged } from '@/types'
import type { PendingAttachment } from '@/components/business/AttachmentUploader.vue'

const { listConversations, listMessages, streamState, setConversation, start, stop, stopAll } = vi.hoisted(() => ({
  listConversations: vi.fn(),
  listMessages: vi.fn(),
  streamState: { value: { streaming: false, interrupted: null, error: null, status: 'idle', phase: 'idle', phaseDetail: null, cancelling: false, taskId: null, messageId: null, partialText: '', segments: [], toolCalls: [], finished: false } },
  setConversation: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  stopAll: vi.fn(),
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
    start,
    stop,
    stopAll,
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
        AgentRunStatus: true,
        'agent-run-status': true,
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
    start.mockReset()
    stop.mockReset()
    stopAll.mockReset()
    streamState.value = { streaming: false, interrupted: null, error: null, status: 'idle', phase: 'idle', phaseDetail: null, cancelling: false, taskId: null, messageId: null, partialText: '', segments: [], toolCalls: [], finished: false }
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

  it('发送请求只传附件 ID，但乐观消息保留附件展示元数据和 file_refs', async () => {
    listMessages.mockResolvedValue(page('c_a', '历史 A'))
    start.mockResolvedValue(undefined)
    const wrapper = mountShell()
    await flushPromises()
    await wrapper.find('[data-conversation-id="c_a"]').trigger('click')
    await flushPromises()

    const vm = wrapper.vm as unknown as {
      input: string
      pendingAttachments: PendingAttachment[]
      fileRefs: FileRef[]
      send: () => Promise<void>
    }
    vm.input = '请读取引用内容'
    vm.pendingAttachments = [{ attachment_id: 'atc_1', name: 'README.md', mime_type: 'text/markdown', size: 42, status: 'uploaded' }]
    vm.fileRefs = [{ path: 'README.md' }]

    await vm.send()
    expect(start).toHaveBeenCalledWith({
      conversation_id: 'c_a',
      workspace_id: 'ws_001',
      message: { content: '请读取引用内容', role: 'user', attachments: ['atc_1'], file_refs: [{ path: 'README.md' }] },
      stream: true,
    })
    const optimistic = (wrapper.vm as unknown as { messages: Message[] }).messages.at(-1)
    expect(optimistic?.attachments).toEqual([
      { attachment_id: 'atc_1', name: 'README.md', mime_type: 'text/markdown', size: 42, status: 'uploaded' },
    ])
    expect(optimistic?.file_refs).toEqual([{ path: 'README.md' }])
  })

  it('切换会话会清理未发送正文、附件、引用、失败草稿和 picker 状态', async () => {
    listMessages.mockResolvedValue(page('c_a', 'A'))
    const wrapper = mountShell()
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      input: string
      pendingAttachments: PendingAttachment[]
      fileRefs: FileRef[]
      lastFailedDraft: unknown
      refPickerVisible: boolean
    }
    vm.input = '只属于 A 的草稿'
    vm.pendingAttachments = [{ attachment_id: 'atc_a', name: 'a.txt', mime_type: 'text/plain', size: 1, status: 'uploaded' }]
    vm.fileRefs = [{ path: 'a.txt' }]
    vm.lastFailedDraft = { content: '失败草稿', attachments: vm.pendingAttachments, refs: vm.fileRefs }
    vm.refPickerVisible = true

    await wrapper.find('[data-conversation-id="c_b"]').trigger('click')
    expect(vm.input).toBe('')
    expect(vm.pendingAttachments).toEqual([])
    expect(vm.fileRefs).toEqual([])
    expect(vm.lastFailedDraft).toBeNull()
    expect(vm.refPickerVisible).toBe(false)
  })

  it('路由复用切换工作区时丢弃旧会话列表响应并停止旧工作区流', async () => {
    let resolveOld!: (value: unknown) => void
    listConversations
      .mockReset()
      .mockImplementationOnce(() => new Promise<unknown>((resolve) => { resolveOld = resolve }))
      .mockResolvedValueOnce({
        items: [{ id: 'c_ws2', title: '工作区 2' }],
        total: 1,
        page: 1,
        page_size: 100,
      })
    const wrapper = mountShell()
    await wrapper.setProps({ workspaceId: 'ws_002' })
    await flushPromises()
    expect(wrapper.find('[data-conversation-id="c_ws2"]').exists()).toBe(true)
    expect(wrapper.find('[data-conversation-id="c_a"]').exists()).toBe(false)
    expect(stopAll).toHaveBeenCalled()

    resolveOld({
      items: [{ id: 'c_ws1-late', title: '旧工作区迟到' }],
      total: 1,
      page: 1,
      page_size: 100,
    })
    await flushPromises()
    expect(wrapper.find('[data-conversation-id="c_ws1-late"]').exists()).toBe(false)
  })
})
