import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { listMcpServers, registerMcp, deleteMcpServer } from '@/api/mcp'
import type { McpRegisterResult, McpServer } from '@/types'
import { useMcpStore } from './mcp'

vi.mock('@/api/mcp', () => ({
  listMcpServers: vi.fn(),
  registerMcp: vi.fn(),
  deleteMcpServer: vi.fn(),
}))

const mockedList = vi.mocked(listMcpServers)
const mockedRegister = vi.mocked(registerMcp)
const mockedDelete = vi.mocked(deleteMcpServer)

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

describe('mcp store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('list 成功写入服务列表并更新状态', async () => {
    mockedList.mockResolvedValueOnce([server])
    const store = useMcpStore()

    await store.list()

    expect(store.servers).toEqual([server])
    expect(store.status).toBe('success')
    expect(store.errorMessage).toBeNull()
  })

  it('list 失败保留旧列表，retry 可恢复', async () => {
    mockedList.mockRejectedValueOnce(new Error('服务不可用'))
    mockedList.mockResolvedValueOnce([])
    const store = useMcpStore()
    store.servers = [server]

    await store.list()
    expect(store.servers).toEqual([server])
    expect(store.status).toBe('error')
    expect(store.errorMessage).toBe('服务不可用')

    await store.retry()
    expect(store.servers).toEqual([])
    expect(store.status).toBe('success-empty')
  })

  it('register 发送完整请求并刷新列表', async () => {
    const result: McpRegisterResult = { server, tools: [] }
    mockedRegister.mockResolvedValueOnce(result)
    mockedList.mockResolvedValueOnce([server])
    const store = useMcpStore()
    const body = {
      name: 'my-gateway',
      url_or_command: server.url_or_command,
      headers: { Authorization: 'secret-token' },
      enable: true,
    }

    await expect(store.register(body)).resolves.toEqual(result)
    expect(mockedRegister).toHaveBeenCalledWith(body)
    expect(mockedList).toHaveBeenCalledTimes(1)
    expect(store.servers).toEqual([server])
  })

  it('remove 成功后刷新列表', async () => {
    mockedDelete.mockResolvedValueOnce(null)
    mockedList.mockResolvedValueOnce([])
    const store = useMcpStore()

    await store.remove('server-1')

    expect(mockedDelete).toHaveBeenCalledWith('server-1')
    expect(mockedList).toHaveBeenCalledTimes(1)
    expect(store.servers).toEqual([])
  })
})
