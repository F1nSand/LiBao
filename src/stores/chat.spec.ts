import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { AttachmentRef, Message, Paged } from '@/types'

const { listMessages } = vi.hoisted(() => ({
  listMessages: vi.fn(),
}))

vi.mock('@/api/chat', () => ({
  listConversations: vi.fn(),
  createConversation: vi.fn(),
  listMessages,
  deleteConversation: vi.fn(),
}))

import { useChatStore } from './chat'

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
  return { items: [message(conversationId, content)], total: 1, page: 1, page_size: 50 }
}

function optimisticUserMessage(conversationId: string, content = '请修改文件'): Message {
  return {
    id: 'local_user_1',
    conversation_id: conversationId,
    role: 'user',
    content,
    attachments: [{ attachment_id: 'att_1', name: '需求.txt' }],
    file_refs: [{ path: 'docs/需求.txt' }],
    tool_calls: [],
    created_at: '2026-08-30T00:00:00.000Z',
  }
}

describe('chat store conversation loading races', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listMessages.mockReset()
  })

  it('A→B→A 时只接受最后一次 A 请求的结果', async () => {
    const requests: Array<{ resolve: (value: Paged<Message>) => void; reject: (error: Error) => void }> = []
    listMessages.mockImplementation(
      () =>
        new Promise<Paged<Message>>((resolve, reject) => {
          requests.push({ resolve, reject })
        }),
    )
    const store = useChatStore()

    const firstA = store.selectConversation('c_a')
    const b = store.selectConversation('c_b')
    const secondA = store.selectConversation('c_a')

    expect(store.currentId).toBe('c_a')
    expect(store.messagesLoading).toBe(true)

    requests[0].resolve(page('c_a', '旧 A 响应'))
    await firstA
    expect(store.currentMessages).toEqual([])
    expect(store.messagesLoading).toBe(true)

    requests[1].resolve(page('c_b', '旧 B 响应'))
    await b
    expect(store.currentMessages).toEqual([])
    expect(store.messagesLoading).toBe(true)

    requests[2].resolve(page('c_a', '最新 A 响应'))
    await secondA
    expect(store.currentMessages.map((item) => item.content)).toEqual(['最新 A 响应'])
    expect(store.messagesLoading).toBe(false)
  })

  it('过期请求失败时不污染当前会话并保持最新 loading 状态', async () => {
    const requests: Array<{ resolve: (value: Paged<Message>) => void; reject: (error: Error) => void }> = []
    listMessages.mockImplementation(
      () =>
        new Promise<Paged<Message>>((resolve, reject) => {
          requests.push({ resolve, reject })
        }),
    )
    const store = useChatStore()

    const first = store.selectConversation('c_a')
    const latest = store.selectConversation('c_b')

    requests[0].reject(new Error('A 请求失败'))
    await first
    expect(store.messagesError).toBeNull()
    expect(store.messagesLoading).toBe(true)

    requests[1].resolve(page('c_b', 'B 响应'))
    await latest
    expect(store.currentMessages.map((item) => item.content)).toEqual(['B 响应'])
    expect(store.messagesError).toBeNull()
    expect(store.messagesLoading).toBe(false)
  })

  it('重试当前会话时清除旧错误并重新进入 loading', async () => {
    let resolveRequest!: (value: Paged<Message>) => void
    listMessages.mockRejectedValueOnce(new Error('首次失败')).mockReturnValueOnce(
      new Promise<Paged<Message>>((resolve) => {
        resolveRequest = resolve
      }),
    )
    const store = useChatStore()

    await store.selectConversation('c_a')
    expect(store.messagesError).toBe('首次失败')
    const retry = store.loadMessages('c_a')
    expect(store.messagesError).toBeNull()
    expect(store.messagesLoading).toBe(true)

    resolveRequest(page('c_a', '重试成功'))
    await retry
    expect(store.currentMessages.map((item) => item.content)).toEqual(['重试成功'])
    expect(store.messagesLoading).toBe(false)
  })

  it('乐观用户消息保留附件展示元数据', () => {
    const store = useChatStore()
    store.currentId = 'c_a'
    const attachment: AttachmentRef = {
      attachment_id: 'atc_1',
      name: '报告.pdf',
      mime_type: 'application/pdf',
      size: 2048,
      status: 'uploaded',
    }

    store.appendUserMessage('请阅读附件', [attachment])

    expect(store.currentMessages[0]?.attachments).toEqual([attachment])
    expect(store.currentMessages[0]?.attachments?.[0]).not.toBe(attachment)
  })

  it('checkpoint anchor 回填当前会话最后一条本地用户消息', () => {
    const store = useChatStore()
    store.currentId = 'c_a'
    const optimistic = optimisticUserMessage('c_a')
    store.currentMessages = [optimistic]

    const result = store.reconcileCheckpointAnchor({
      conversationId: 'c_a',
      userMessageId: 'user_1',
      checkpointId: 'checkpoint_1',
    })

    expect(result).toBe(true)
    expect(store.currentMessages).toHaveLength(1)
    expect(store.currentMessages[0]).toMatchObject({
      id: 'user_1',
      checkpoint_id: 'checkpoint_1',
      content: '请修改文件',
      attachments: optimistic.attachments,
      file_refs: optimistic.file_refs,
    })
  })

  it('重复回放同一 checkpoint anchor 不追加消息且稳定 no-op', () => {
    const store = useChatStore()
    store.currentId = 'c_a'
    store.currentMessages = [optimisticUserMessage('c_a')]
    const anchor = { conversationId: 'c_a', userMessageId: 'user_1', checkpointId: 'checkpoint_1' }

    expect(store.reconcileCheckpointAnchor(anchor)).toBe(true)
    expect(store.reconcileCheckpointAnchor(anchor)).toBe(false)
    expect(store.currentMessages).toHaveLength(1)
    expect(store.currentMessages[0]?.id).toBe('user_1')
    expect(store.currentMessages[0]?.checkpoint_id).toBe('checkpoint_1')
  })

  it('忽略其他会话、没有本地用户消息或已有不同 checkpoint 的 anchor', () => {
    const store = useChatStore()
    store.currentId = 'c_a'
    const optimistic = optimisticUserMessage('c_a')
    store.currentMessages = [optimistic]

    expect(store.reconcileCheckpointAnchor({
      conversationId: 'c_b', userMessageId: 'user_b', checkpointId: 'checkpoint_b',
    })).toBe(false)
    expect(store.currentMessages[0]).toMatchObject(optimistic)

    store.currentMessages = [message('c_a', 'assistant')]
    expect(store.reconcileCheckpointAnchor({
      conversationId: 'c_a', userMessageId: 'user_a', checkpointId: 'checkpoint_a',
    })).toBe(false)
    expect(store.currentMessages[0]?.id).toBe('c_a-assistant')

    const anchored = optimisticUserMessage('c_a')
    anchored.id = 'user_existing'
    anchored.checkpoint_id = 'checkpoint_existing'
    store.currentMessages = [anchored]
    expect(store.reconcileCheckpointAnchor({
      conversationId: 'c_a', userMessageId: 'user_new', checkpointId: 'checkpoint_new',
    })).toBe(false)
    expect(store.currentMessages[0]).toMatchObject(anchored)
  })
})
