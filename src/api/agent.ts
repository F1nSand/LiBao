import { httpGet, httpPost, httpPut, httpDelete } from './http'
import type { Paged, Agent, AgentConfigInput, AgentVersion } from '@/types'

export function listAgents(params: { page?: number; page_size?: number } = {}) {
  return httpGet<Paged<Agent>>('/agents', { params })
}

export function getAgent(id: string) {
  return httpGet<Agent>(`/agents/${id}`)
}

export function createAgent(body: AgentConfigInput) {
  return httpPost<Agent>('/agents', body)
}

export function updateAgent(id: string, body: AgentConfigInput) {
  return httpPut<Agent>(`/agents/${id}`, body)
}

export function deleteAgent(id: string) {
  return httpDelete<null>(`/agents/${id}`)
}

export function listAgentVersions(id: string) {
  return httpGet<AgentVersion[]>(`/agents/${id}/versions`)
}

export function publishAgent(id: string) {
  return httpPost<Agent>(`/agents/${id}/publish`)
}

export function unpublishAgent(id: string) {
  return httpPost<Agent>(`/agents/${id}/unpublish`)
}
