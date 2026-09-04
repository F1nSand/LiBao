import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ToolDefinition } from '@/types'
import { listTools, toggleTool } from '@/api/tool'
import { useToolStore } from './tool'

vi.mock('@/api/tool', () => ({
  listTools: vi.fn(),
  toggleTool: vi.fn(),
  createTool: vi.fn(),
  updateTool: vi.fn(),
  deleteTool: vi.fn(),
  testTool: vi.fn(),
  searchTools: vi.fn(),
}))

const mockedListTools = vi.mocked(listTools)
const mockedToggleTool = vi.mocked(toggleTool)
const tool = { id: 'tool-1', name: 'calc', tool_type: 'execution', enabled: false, created_at: '' } as ToolDefinition

describe('tool store list status', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedListTools.mockReset()
    mockedToggleTool.mockReset()
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

  it('toggle 成功后原地替换目标行，不重新加载列表', async () => {
    const store = useToolStore()
    store.tools = [tool]
    const updated = { ...tool, enabled: true }
    mockedToggleTool.mockResolvedValueOnce(updated)

    await expect(store.toggle(tool.id, true)).resolves.toEqual(updated)

    expect(store.tools).toEqual([updated])
    expect(mockedListTools).not.toHaveBeenCalled()
  })

  it('toggleMany 汇总全部成功和部分失败，不覆盖失败项', async () => {
    const store = useToolStore()
    const second = { ...tool, id: 'tool-2', name: 'fetch', enabled: false }
    store.tools = [tool, second]
    const updated = { ...tool, enabled: true }
    mockedToggleTool.mockResolvedValueOnce(updated).mockRejectedValueOnce(new Error('服务不可用'))

    await expect(store.toggleMany([tool.id, second.id], true)).resolves.toMatchObject({
      succeeded: [updated],
      failed: [{ id: second.id }],
    })

    expect(store.tools).toEqual([updated, second])
    expect(mockedListTools).not.toHaveBeenCalled()
  })
})
