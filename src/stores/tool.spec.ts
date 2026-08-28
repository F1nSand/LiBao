import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ToolDefinition } from '@/types'
import { listTools } from '@/api/tool'
import { useToolStore } from './tool'

vi.mock('@/api/tool', () => ({
  listTools: vi.fn(),
  toggleTool: vi.fn(),
  createTool: vi.fn(),
  updateTool: vi.fn(),
  deleteTool: vi.fn(),
  testTool: vi.fn(),
  registerMcp: vi.fn(),
  searchTools: vi.fn(),
}))

const mockedListTools = vi.mocked(listTools)
const tool = { id: 'tool-1', name: 'calc', tool_type: 'execution', enabled: false, created_at: '' } as ToolDefinition

describe('tool store list status', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedListTools.mockReset()
  })

  it('请求失败时保留旧列表，不伪装成空成功；retry 可恢复', async () => {
    const store = useToolStore()
    store.tools = [tool]
    mockedListTools.mockRejectedValueOnce(new Error('服务不可用'))

    await store.list()

    expect(store.tools).toEqual([tool])
    expect(store.status).toBe('error')
    expect(store.errorMessage).toBe('服务不可用')

    mockedListTools.mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 100 })
    await store.retry()
    expect(store.status).toBe('success-empty')
    expect(store.errorMessage).toBeNull()
  })
})
