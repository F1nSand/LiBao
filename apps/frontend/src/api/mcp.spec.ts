import { beforeEach, describe, expect, it, vi } from 'vitest'
import { httpDelete, httpGet, httpPost } from './http'
import { deleteMcpServer, listMcpServers, registerMcp } from './mcp'
import type { McpRegisterRequest, McpRegisterResult, McpServer } from '@/types'

vi.mock('./http', () => ({
  httpDelete: vi.fn(),
  httpGet: vi.fn(),
  httpPost: vi.fn(),
}))

const mockedGet = vi.mocked(httpGet)
const mockedPost = vi.mocked(httpPost)
const mockedDelete = vi.mocked(httpDelete)

const server: McpServer = {
  id: 'server-1',
  name: 'my-gateway',
  transport: 'http',
  url_or_command: 'http://gateway.local/mcp',
  header_names: ['Authorization'],
  enabled: true,
  tool_count: 2,
  created_at: '2026-09-03T00:00:00Z',
}

describe('api/mcp', () => {
  beforeEach(() => vi.clearAllMocks())

  it('listMcpServers 请求 MCP 列表并保留 header_names 契约', async () => {
    mockedGet.mockResolvedValueOnce([server])

    await expect(listMcpServers()).resolves.toEqual([server])
    expect(mockedGet).toHaveBeenCalledWith('/tools/mcp')
  })

  it('registerMcp 发送名称、地址、请求头和启用状态', async () => {
    const body: McpRegisterRequest = {
      name: 'my-gateway',
      url_or_command: 'http://gateway.local/mcp',
      headers: { Authorization: 'secret-token' },
      enable: true,
    }
    const result: McpRegisterResult = { server, tools: [] }
    mockedPost.mockResolvedValueOnce(result)

    await expect(registerMcp(body)).resolves.toEqual(result)
    expect(mockedPost).toHaveBeenCalledWith('/tools/mcp/register', body)
  })

  it('deleteMcpServer 删除指定服务并返回 null', async () => {
    mockedDelete.mockResolvedValueOnce(null)

    await expect(deleteMcpServer('server-1')).resolves.toBeNull()
    expect(mockedDelete).toHaveBeenCalledWith('/tools/mcp/server-1')
  })
})
