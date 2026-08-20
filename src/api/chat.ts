import { httpGet, httpPost, httpDelete } from './http'
import type { Paged, Conversation, Message, CreateConversationRequest } from '@/types'

export interface PageParams {
  page?: number
  page_size?: number
}

/** 会话列表查询参数（M7-B：workspace_id 过滤工作区会话） */
export interface ConversationQuery extends PageParams {
  workspace_id?: string
}

export function listConversations(params: ConversationQuery = {}) {
  return httpGet<Paged<Conversation>>('/conversations', { params })
}

export function createConversation(body: CreateConversationRequest) {
  return httpPost<Conversation>('/conversations', body)
}

export function getConversation(id: string) {
  return httpGet<Conversation>(`/conversations/${id}`)
}

export function listMessages(id: string, params: PageParams = {}) {
  return httpGet<Paged<Message>>(`/conversations/${id}/messages`, { params })
}

export function deleteConversation(id: string) {
  return httpDelete<null>(`/conversations/${id}`)
}
