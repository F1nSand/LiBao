import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { LongTermMemory } from '@/types'
import { listLongterm } from '@/api/memory'
import { useMemoryStore } from './memory'

vi.mock('@/api/memory', () => ({
  listLongterm: vi.fn(),
  createLongterm: vi.fn(),
  listLongtermVersions: vi.fn(),
  deleteLongterm: vi.fn(),
  maintenance: vi.fn(),
}))

const mockedListLongterm = vi.mocked(listLongterm)
const memory = { id: 'mem-1', card_type: 'note', title: '决策', body: '内容', created_at: '' } as LongTermMemory

describe('memory store list status', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedListLongterm.mockReset()
  })

  it('加载失败时保留旧记忆，retry 成功后更新为空态', async () => {
    const store = useMemoryStore()
    store.longterm = [memory]
    mockedListLongterm.mockRejectedValueOnce(new Error('记忆接口失败'))

    await store.listLongterm()
    expect(store.longterm).toEqual([memory])
    expect(store.status).toBe('error')
    expect(store.errorMessage).toBe('记忆接口失败')

    mockedListLongterm.mockResolvedValueOnce([])
    await store.retry()
    expect(store.status).toBe('success-empty')
    expect(store.longterm).toEqual([])
  })
})
