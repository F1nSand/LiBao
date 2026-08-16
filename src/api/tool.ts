import { httpGet, httpPost, httpPut, httpPatch, httpDelete } from './http'
import type {
  Paged,
  ToolDefinition,
  CreateToolRequest,
  ToolTestResult,
  ToolSearchHit,
  McpRegisterRequest,
} from '@/types'

export function listTools(params: { page?: number; page_size?: number; enabled?: boolean } = {}) {
  return httpGet<Paged<ToolDefinition>>('/tools', { params })
}

export function getTool(id: string) {
  return httpGet<ToolDefinition>(`/tools/${id}`)
}

export function createTool(body: CreateToolRequest) {
  return httpPost<ToolDefinition>('/tools', body)
}

export function updateTool(id: string, body: Partial<CreateToolRequest>) {
  return httpPut<ToolDefinition>(`/tools/${id}`, body)
}

export function toggleTool(id: string, enabled: boolean) {
  return httpPatch<ToolDefinition>(`/tools/${id}`, { enabled })
}

export function deleteTool(id: string) {
  return httpDelete<null>(`/tools/${id}`)
}

export function testTool(id: string, params: Record<string, unknown>) {
  return httpPost<ToolTestResult>(`/tools/${id}/test`, { params })
}

export function registerMcp(body: McpRegisterRequest) {
  return httpPost<ToolDefinition>('/tools/mcp/register', body)
}

export function searchTools(q: string) {
  return httpGet<ToolSearchHit[]>(`/tools/search`, { params: { q } })
}
