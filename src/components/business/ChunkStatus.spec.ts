import { describe, it, expect, vi, beforeEach } from 'vitest'
import { shallowMount, flushPromises } from '@vue/test-utils'
import ChunkStatus from './ChunkStatus.vue'
import type { KbDocument } from '@/types'

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
}))
vi.mock('@/stores/kb', () => ({
  useKbStore: vi.fn(() => ({ status: mocks.status })),
}))

const uploadedDoc: KbDocument = {
  id: 'kbd_new',
  collection_id: 'kbc_001',
  name: '上传.md',
  mime_type: 'text/markdown',
  size: 2048,
  status: 'uploaded',
  chunk_count: 0,
  progress: 0,
  created_at: '2026-08-19T00:00:00Z',
}

describe('ChunkStatus 上传态轮询 + live 回传（修复：uploaded 卡「已上传」）', () => {
  beforeEach(() => {
    mocks.status.mockReset()
  })

  it('uploaded 触发轮询（旧实现漏 uploaded 不启动）', async () => {
    mocks.status.mockResolvedValue({ status: 'uploaded', chunk_count: 0, progress: 0 })
    const w = shallowMount(ChunkStatus, { props: { document: uploadedDoc } })
    await flushPromises()
    expect(mocks.status).toHaveBeenCalledWith('kbd_new')
    expect(w.find('.chunk-status').text()).toContain('已上传')
  })

  it('轮询到 chunking：live 渲染 + 回传 status-change', async () => {
    mocks.status.mockResolvedValue({ status: 'chunking', chunk_count: 2, progress: 40 })
    const w = shallowMount(ChunkStatus, { props: { document: uploadedDoc } })
    await flushPromises()
    expect(w.find('.chunk-status').text()).toContain('分块中')
    expect(w.find('.chunk-status').text()).toContain('2 chunks')
    const emits = w.emitted('status-change')
    expect(emits).toBeTruthy()
    expect(emits![0][0]).toMatchObject({ id: 'kbd_new', status: 'chunking', chunk_count: 2, progress: 40 })
  })

  it('indexed 终态不启动轮询', async () => {
    const indexed: KbDocument = { ...uploadedDoc, status: 'indexed', chunk_count: 5, progress: 100 }
    const w = shallowMount(ChunkStatus, { props: { document: indexed } })
    await flushPromises()
    expect(mocks.status).not.toHaveBeenCalled()
    expect(w.find('.chunk-status').text()).toContain('已索引')
  })

  it('uploaded → 轮询推进到 indexed：标签/分块数收敛 + 回传 + 停轮询', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    mocks.status
      .mockResolvedValueOnce({ status: 'chunking', chunk_count: 2, progress: 40 })
      .mockResolvedValue({ status: 'indexed', chunk_count: 5, progress: 100 })
    const w = shallowMount(ChunkStatus, { props: { document: uploadedDoc } })
    await flushPromises()
    expect(w.find('.chunk-status').text()).toContain('分块中')

    vi.advanceTimersByTime(3000) // 触发 interval 轮询
    await flushPromises()

    expect(w.find('.chunk-status').text()).toContain('已索引')
    expect(w.find('.chunk-status').text()).toContain('5 chunks')
    const emits = w.emitted('status-change')
    expect(emits!.at(-1)![0]).toMatchObject({ status: 'indexed', chunk_count: 5 })
    vi.useRealTimers()
  })
})
