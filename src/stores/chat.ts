import { defineStore } from 'pinia'
import {
  listConversations,
  createConversation as apiCreateConversation,
  listMessages,
  deleteConversation as apiDeleteConversation,
} from '@/api/chat'
import type { AttachmentRef, Conversation, Message } from '@/types'

/**
 * chat store（docs/02 §7）：只存客户端状态（会话列表/选中态/消息列表），
 * 不复制服务端全量；流式状态由组件持有的 useChatStream 管理。
 * 单通用 Agent：会话不携带 agent，chat/conversation 固定用后端默认通用 Agent。
 */
export const useChatStore = defineStore('chat', {
  state: () => ({
    conversations: [] as Conversation[],
    currentId: null as string | null,
    currentMessages: [] as Message[],
    messagesLoading: false,
    messagesError: null as string | null,
    /** 消息请求版本：只允许最后一次加载请求提交状态，覆盖 A→B→A 回切竞态。 */
    messagesRequestVersion: 0,
    convTotal: 0,
    page: 1,
    pageSize: 50,
  }),
  getters: {
    currentConversation: (s) => s.conversations.find((c) => c.id === s.currentId) ?? null,
  },
  actions: {
    async loadConversations(page = 1) {
      const res = await listConversations({ page, page_size: this.pageSize })
      this.conversations = res.items
      this.convTotal = res.total
      this.page = res.page
    },

    async createConversation(title: string) {
      const c = await apiCreateConversation({ title })
      this.conversations.unshift(c)
      this.messagesRequestVersion += 1
      this.currentId = c.id
      this.currentMessages = []
      this.messagesLoading = false
      this.messagesError = null
    },

    async selectConversation(id: string) {
      this.currentId = id
      this.currentMessages = []
      this.messagesError = null
      await this.loadMessages(id)
    },

    async loadMessages(id: string, page = 1) {
      const requestVersion = ++this.messagesRequestVersion
      this.messagesLoading = true
      if (id === this.currentId) this.messagesError = null
      try {
        const res = await listMessages(id, { page, page_size: 50 })
        if (requestVersion !== this.messagesRequestVersion || id !== this.currentId) return
        this.currentMessages = res.items
      } catch (e) {
        if (requestVersion === this.messagesRequestVersion && id === this.currentId) {
          this.messagesError = e instanceof Error ? e.message : '消息加载失败'
        }
      } finally {
        if (requestVersion === this.messagesRequestVersion && id === this.currentId) this.messagesLoading = false
      }
    },

    async deleteConversation(id: string) {
      await apiDeleteConversation(id)
      this.conversations = this.conversations.filter((c) => c.id !== id)
      if (this.currentId === id) {
        this.messagesRequestVersion += 1
        this.currentId = null
        this.currentMessages = []
        this.messagesLoading = false
        this.messagesError = null
      }
    },

    /** 乐观追加用户消息（stream 由视图负责） */
    appendUserMessage(content: string, attachments: AttachmentRef[] = []) {
      const msg: Message = {
        id: `local_${Date.now()}`,
        conversation_id: this.currentId ?? '',
        role: 'user',
        content,
        attachments: attachments.map((attachment) => ({ ...attachment })),
        tool_calls: [],
        created_at: new Date().toISOString(),
      }
      this.currentMessages.push(msg)
    },

    /** 追加助手消息（onPersistedMessage 用流式状态补齐 content 后调用，防 done 后文本气泡消失） */
    appendAssistantMessage(msg: Message) {
      this.currentMessages.push(msg)
    },
  },
})
