import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { SystemLog } from '@/types'
import { listLogs } from '@/api/system'
import { useSystemStore } from './system'

vi.mock('@/api/system', () => ({
  listLogs: vi.fn(),
  getTrace: vi.fn(),
}))

const mockedListLogs = vi.mocked(listLogs)
const log = { id: 'log-1', trace_id: 'trace-1', level: 'INFO', event: 'run', created_at: '' } as SystemLog

describe('system store list status', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedListLogs.mockReset()
  })

  it('查询失败时保留旧日志，retry 可恢复且记录最近筛选条件', async () => {
    const store = useSystemStore()
    store.logs = [log]
    mockedListLogs.mockRejectedValueOnce(new Error('日志服务失败'))

    await store.listLogs({ trace_id: 'trace-1', level: 'ERROR' })
    expect(store.logs).toEqual([log])
    expect(store.status).toBe('error')
    expect(store.errorMessage).toBe('日志服务失败')

    mockedListLogs.mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 20 })
    await store.retry()
    expect(store.status).toBe('success-empty')
    expect(mockedListLogs).toHaveBeenLastCalledWith({ page: 1, page_size: 20, trace_id: 'trace-1', level: 'ERROR' })
  })
})
