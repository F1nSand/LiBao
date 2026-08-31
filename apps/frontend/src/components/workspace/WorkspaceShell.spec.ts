import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'
import type { CheckpointAnchor, ComposerAttachment, FileRef, Message, Paged, RestoreResult } from '@/types'
import type { PendingAttachment } from '@/components/business/AttachmentUploader.vue'

const { listConversations, listMessages, streamState, streamOptions, setConversation, start, stop, stopAll, resetConversation, reconcileTaskTerminal, useChatStream } = vi.hoisted(() => ({
  listConversations: vi.fn(),
  listMessages: vi.fn(),
  streamState: { value: { streaming: false, interrupted: null, error: null, status: 'idle', phase: 'idle', phaseDetail: null, cancelling: false, taskId: null, messageId: null, partialText: '', segments: [], toolCalls: [], finished: false } },
  streamOptions: { value: null as { onCheckpointAnchor?: (anchor: CheckpointAnchor) => void } | null },
  setConversation: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  stopAll: vi.fn(),
  resetConversation: vi.fn(),
  reconcileTaskTerminal: vi.fn(),
  useChatStream: vi.fn(),
}))

vi.mock('@/api/chat', () => ({
  listConversations,
  createConversation: vi.fn(),
  listMessages,
  deleteConversation: vi.fn(),
}))
vi.mock('@/composables/useChatStream', () => ({
  useChatStream: useChatStream.mockImplementation((options: { onCheckpointAnchor?: (anchor: CheckpointAnchor) => void }) => {
    streamOptions.value = options
    return {
    state: streamState,
    setConversation,
    start,
    stop,
    stopAll,
    resetConversation,
    reconcileTaskTerminal,
    confirmInterrupt: vi.fn(),
    }
  }),
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

function checkpointUserMessage(conversationId: string, id = `${conversationId}-user`): Message {
  return {
    id,
    conversation_id: conversationId,
    role: 'user',
    content: '回滚到这里',
    checkpoint_id: 'cp_1',
    checkpoint: { id: 'cp_1', status: 'sealed', changed_file_count: 0, can_restore_code: true, can_restore_conversation: true },
    tool_calls: [],
    created_at: '2026-08-30T00:00:00.000Z',
  }
}

function streamValue(overrides: Record<string, unknown> = {}) {
  return reactive({
    streaming: false,
    interrupted: null,
    error: null,
    status: 'idle',
    phase: 'idle',
    phaseDetail: null,
    cancelling: false,
    taskId: null,
    messageId: null,
    partialText: '',
    segments: [],
    toolCalls: [],
    finished: false,
    ...overrides,
  })
}

function mountShell() {
  return mount(WorkspaceShell, {
    props: { workspaceId: 'ws_001' },
    global: {
      stubs: {
        ResourceManager: true,
        TrajectoryPanel: true,
        AttachmentUploader: true,
        ModelPicker: { template: '<button class="model-picker-stub" aria-label="选择模型">模型</button>' },
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
          template: `<div data-testid="messages" :data-loading="loading">
            {{ messages.map((item) => item.content).join("|") }}
            <button v-if="messages.length && messages[messages.length - 1].checkpoint_id" data-testid="rollback" @click="$emit('rollback', messages[messages.length - 1])">rollback</button>
          </div>`,
        },
        CheckpointRestoreDialog: {
          props: ['modelValue', 'conversationId', 'target'],
          template: `<div v-if="modelValue" data-testid="restore-dialog" :data-conversation-id="conversationId" :data-checkpoint-id="target?.checkpointId">
            <button data-testid="restore-complete" @click="$emit('completed', { status: 'completed', conversation: { action: 'restore_cursor' } })">complete</button>
          </div>`,
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
    resetConversation.mockReset()
    reconcileTaskTerminal.mockReset()
    streamState.value = streamValue()
    streamOptions.value = null
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

  it('消息列表发出 rollback 后打开 checkpoint restore dialog', async () => {
    listMessages.mockResolvedValue({ items: [checkpointUserMessage('c_a')], total: 1, page: 1, page_size: 100 })
    const wrapper = mountShell()
    await flushPromises()
    await wrapper.find('[data-conversation-id="c_a"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="rollback"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="restore-dialog"]').attributes('data-conversation-id')).toBe('c_a')
    expect(wrapper.get('[data-testid="restore-dialog"]').attributes('data-checkpoint-id')).toBe('cp_1')
  })

  it('回滚时若停止后仍在运行，不打开 dialog', async () => {
    listMessages.mockResolvedValue({ items: [checkpointUserMessage('c_a')], total: 1, page: 1, page_size: 100 })
    streamState.value = streamValue({ streaming: true })
    stop.mockResolvedValue('cancelled')
    const wrapper = mountShell()
    await flushPromises()
    await wrapper.find('[data-conversation-id="c_a"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="rollback"]').trigger('click')
    await flushPromises()

    expect(stop).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="restore-dialog"]').exists()).toBe(false)
  })

  it('restore completed 后关闭 dialog 并重新加载消息和工作区会话', async () => {
    listMessages
      .mockResolvedValueOnce({ items: [checkpointUserMessage('c_a')], total: 1, page: 1, page_size: 100 })
      .mockResolvedValueOnce({ items: [message('c_a', '恢复后的消息')], total: 1, page: 1, page_size: 100 })
    const wrapper = mountShell()
    await flushPromises()
    await wrapper.find('[data-conversation-id="c_a"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="rollback"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="restore-complete"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="restore-dialog"]').exists()).toBe(false)
    expect(listMessages).toHaveBeenCalledTimes(2)
    expect(listConversations).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="messages"]').text()).toContain('恢复后的消息')
  })

  it('conversation restore 按权威 action 裁剪消息并恢复正文、附件和 file_refs 草稿', async () => {
    const before = message('c_a', '保留消息')
    const target = checkpointUserMessage('c_a', 'target')
    const after = message('c_a', '应移除消息')
    listMessages
      .mockResolvedValueOnce({ items: [before, target, after], total: 3, page: 1, page_size: 100 })
      .mockResolvedValueOnce({ items: [before], total: 1, page: 1, page_size: 100 })
    const wrapper = mountShell()
    await flushPromises()
    await wrapper.find('[data-conversation-id="c_a"]').trigger('click')
    await flushPromises()

    const result: RestoreResult = {
      operation_id: 'op_1',
      preview_id: 'preview_1',
      client_request_id: 'request_1',
      mode: 'both',
      target_message_id: 'target',
      status: 'partial',
      restored_files: 0,
      deleted_files: 0,
      skipped_conflicts: [],
      conversation: {
        action: 'withdraw_from_target',
        active_message_head_after_id: 'c_a-保留消息',
        withdrawn_from_message_id: 'target',
        hidden_message_count: 2,
        draft: {
          source_message_id: 'target',
          content: '恢复到工作区',
          attachments: [{ attachment_id: 'a_restore', name: '需求.txt', available: false, unavailable_reason: '附件丢失' }],
          file_refs: [{ path: 'docs/需求.txt' }],
        },
      },
      undo_available: true,
      history_revision: 3,
    }
    await (wrapper.vm as unknown as { onRestoreCompleted: (value: RestoreResult) => Promise<void> }).onRestoreCompleted(result)
    await flushPromises()

    expect(resetConversation).toHaveBeenCalledWith('c_a')
    expect((wrapper.vm as unknown as { input: string }).input).toBe('恢复到工作区')
    expect((wrapper.vm as unknown as { pendingAttachments: ComposerAttachment[] }).pendingAttachments[0]).toMatchObject({ available: false, unavailable_reason: '附件丢失' })
    expect((wrapper.vm as unknown as { fileRefs: FileRef[] }).fileRefs).toEqual([{ path: 'docs/需求.txt' }])
    expect(wrapper.get('[data-testid="messages"]').text()).toBe('保留消息')
  })

  it('首帧 anchor 只回填当前工作区会话的最后一条本地用户消息，replay 不增消息', async () => {
    listMessages.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
    const wrapper = mountShell()
    await flushPromises()
    await wrapper.find('[data-conversation-id="c_a"]').trigger('click')
    await flushPromises()

    const vm = wrapper.vm as unknown as { messages: Message[]; currentId: string | null }
    vm.messages.push({
      id: 'local_workspace_user',
      conversation_id: 'c_a',
      role: 'user',
      content: '创建文件',
      tool_calls: [],
      created_at: '2026-08-30T00:00:00.000Z',
    })
    const onCheckpointAnchor = streamOptions.value?.onCheckpointAnchor
    expect(onCheckpointAnchor).toBeDefined()

    onCheckpointAnchor!({ conversationId: 'c_b', userMessageId: 'user_b', checkpointId: 'cp_b' })
    expect(vm.messages[0]?.id).toBe('local_workspace_user')
    onCheckpointAnchor!({ conversationId: 'c_a', userMessageId: 'user_a', checkpointId: 'cp_a' })
    onCheckpointAnchor!({ conversationId: 'c_a', userMessageId: 'user_a', checkpointId: 'cp_a' })

    expect(vm.messages).toHaveLength(1)
    expect(vm.messages[0]).toMatchObject({ id: 'user_a', checkpoint_id: 'cp_a', content: '创建文件' })
  })
})
