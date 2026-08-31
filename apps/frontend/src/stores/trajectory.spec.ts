import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { TrajectoryDetail } from '@/types'
import { resetUnavailable } from '@/api/availability'
import { getTrajectory } from '@/api/trajectory'
import { useTrajectoryStore } from './trajectory'

vi.mock('@/api/trajectory', () => ({
  getTrajectory: vi.fn(),
}))

const mockedGetTrajectory = vi.mocked(getTrajectory)

function detail(conversationId = 'c1', seq = 1): TrajectoryDetail {
  return {
    conversation_id: conversationId,
    nodes: [{ seq, kind: 'user', time: seq * 1000, content: `消息 ${seq}` }],
    has_more: false,
  }
}

describe('trajectory store loading states', () => {
  beforeEach(() => {
    resetUnavailable()
    setActivePinia(createPinia())
    mockedGetTrajectory.mockReset()
  })

  it('同一初始加载未完成时只发出一次请求', async () => {
    let resolveRequest: ((value: TrajectoryDetail) => void) | undefined
    mockedGetTrajectory.mockReturnValueOnce(
      new Promise<TrajectoryDetail>((resolve) => {
        resolveRequest = resolve
      }),
    )
    const store = useTrajectoryStore()

    const first = store.load('c1')
    const second = store.load('c1')

    expect(mockedGetTrajectory).toHaveBeenCalledTimes(1)
    expect(store.initialLoading).toBe(true)
    resolveRequest?.(detail())
    await Promise.all([first, second])
    expect(store.initialLoading).toBe(false)
    expect(store.detail?.conversation_id).toBe('c1')
  })

  it('实时刷新失败时保留已有轨迹并暴露可恢复错误', async () => {
    mockedGetTrajectory.mockResolvedValueOnce(detail())
    const store = useTrajectoryStore()
    await store.load('c1')

    mockedGetTrajectory.mockRejectedValueOnce(new Error('offline'))
    await store.load('c1')

    expect(store.detail?.nodes[0].content).toBe('消息 1')
    expect(store.refreshing).toBe(false)
    expect(store.error).toBe(true)
    expect(store.errorMessage).toContain('轨迹加载失败')
  })

  it('加载更早期间使用独立状态，成功后 prepend 节点', async () => {
    mockedGetTrajectory.mockResolvedValueOnce({ ...detail('c1', 3), has_more: true })
    const store = useTrajectoryStore()
    await store.load('c1')

    let resolveEarlier: ((value: TrajectoryDetail) => void) | undefined
    mockedGetTrajectory.mockReturnValueOnce(
      new Promise<TrajectoryDetail>((resolve) => {
        resolveEarlier = resolve
      }),
    )
    const pending = store.loadEarlier('c1')
    expect(store.loadingEarlier).toBe(true)
    resolveEarlier?.({ ...detail('c1', 2), has_more: false })
    await pending

    expect(store.loadingEarlier).toBe(false)
    expect(store.detail?.nodes.map((node) => node.seq)).toEqual([2, 3])
    expect(store.hasMore).toBe(false)
  })
})
