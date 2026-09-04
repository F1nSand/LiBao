import { httpDelete, httpGet, httpPost } from './http'
import type { McpRegisterRequest, McpRegisterResult, McpServer } from '@/types'

export function listMcpServers() {
  return httpGet<McpServer[]>('/tools/mcp')
}

export function registerMcp(body: McpRegisterRequest) {
  return httpPost<McpRegisterResult>('/tools/mcp/register', body)
}

export function deleteMcpServer(id: string) {
  return httpDelete<null>(`/tools/mcp/${id}`)
}
