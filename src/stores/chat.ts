import { defineStore } from 'pinia'
import {
  listConversations,
  createConversation as apiCreateConversation,
  listMessages,
  deleteConversation as apiDeleteConversation,
} from '@/api/chat'
import { useAgentStore } from './agent'
import type { Conversation, Message } from '@/types'

/**
 * chat store（docs/02 §7）：只存客户端状态（会话列表/选中态/消息列表），
 * 不复制服务端全量；Agent 列表由 agent store 单一数据源提供（避免双份漂移）。
 * 流式状态由组件持有的 useChatStream 管理。
 */
export const useChatStore = defineStore('chat', {
  state: () => ({
    conversations: [] as Conversation[],
    currentId: null as string | null,
    currentMessages: [] as Message[],
    currentAgentId: '',
    /** 侧栏选中会话的令牌（ChatView 监听以复位流式，创建会话不递增） */
    selectionToken: 0,
    convTotal: 0,
    page: 1,
    pageSize: 50,
  }),
  getters: {
    currentConversation: (s) => s.conversations.find((c) => c.id === s.currentId) ?? null,
    /** 当前 Agent：选中优先，兜底 agent store 首个 */
    activeAgentId: (s) => s.currentAgentId || useAgentStore().agents[0]?.id || '',
  },
  actions: {
    async loadConversations(page = 1) {
      const res = await listConversations({ page, page_size: this.pageSize })
      this.conversations = res.items
      this.convTotal = res.total
      this.page = res.page
    },

    async createConversation(title: string, agentId: string) {
      const c = await apiCreateConversation({ title, agent_id: agentId })
      this.conversations.unshift(c)
      this.currentId = c.id
      this.currentAgentId = agentId
      this.currentMessages = []
    },

    async selectConversation(id: string) {
      this.currentId = id
      this.selectionToken += 1
      await this.loadMessages(id)
    },

    async loadMessages(id: string, page = 1) {
      const res = await listMessages(id, { page, page_size: 50 })
      this.currentMessages = res.items
    },

    async deleteConversation(id: string) {
      await apiDeleteConversation(id)
      this.conversations = this.conversations.filter((c) => c.id !== id)
      if (this.currentId === id) {
        this.currentId = null
        this.currentMessages = []
      }
    },

    /** 乐观追加用户消息（stream 由视图负责） */
    appendUserMessage(content: string, attachmentIds: string[] = []) {
      const msg: Message = {
        id: `local_${Date.now()}`,
        conversation_id: this.currentId ?? '',
        role: 'user',
        content,
        attachments: attachmentIds.map((id) => ({ attachment_id: id })),
        tool_calls: [],
        created_at: new Date().toISOString(),
      }
      this.currentMessages.push(msg)
    },

    /** 追加助手消息（onPersistedMessage 用流式状态补齐 content 后调用，防 done 后文本气泡消失） */
    appendAssistantMessage(msg: Message) {
      this.currentMessages.push(msg)
    },

    setAgent(id: string) {
      this.currentAgentId = id
    },
  },
})
