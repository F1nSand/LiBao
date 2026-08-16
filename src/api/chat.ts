import { httpGet, httpPost, httpDelete } from './http'
import type { Paged, Conversation, Message, CreateConversationRequest } from '@/types'

export interface PageParams {
  page?: number
  page_size?: number
}

export function listConversations(params: PageParams = {}) {
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
