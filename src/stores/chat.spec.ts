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
})
