import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { KbCollection, KbDocument } from '@/types'
import { listCollections, listDocuments } from '@/api/kb'
import { useKbStore } from './kb'

vi.mock('@/api/kb', () => ({
  listCollections: vi.fn(),
  createCollection: vi.fn(),
  deleteCollection: vi.fn(),
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  getDocumentStatus: vi.fn(),
  reindexDocument: vi.fn(),
  archiveDocument: vi.fn(),
  deleteDocument: vi.fn(),
  searchKb: vi.fn(),
}))

const mockedListCollections = vi.mocked(listCollections)
const mockedListDocuments = vi.mocked(listDocuments)
const collection = { id: 'kb-1', name: '知识库', created_at: '' } as KbCollection
const document = { id: 'doc-1', collection_id: 'kb-1', name: 'a.md', status: 'indexed', created_at: '' } as KbDocument

describe('kb store list status', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockedListCollections.mockReset()
    mockedListDocuments.mockReset()
  })

  it('集合请求失败时保留旧数据，retry 会恢复集合与文档列表', async () => {
    const store = useKbStore()
    store.collections = [collection]
    store.currentCollectionId = collection.id
    store.documents = [document]
    mockedListCollections.mockRejectedValueOnce(new Error('集合接口失败'))

    await store.listCollections()

    expect(store.collections).toEqual([collection])
    expect(store.documents).toEqual([document])
    expect(store.listStatus).toBe('error')
    expect(store.errorMessage).toBe('集合接口失败')

    mockedListCollections.mockResolvedValueOnce([collection])
    await store.retry()
    expect(store.listStatus).toBe('success')
    expect(store.errorMessage).toBeNull()
  })

  it('切换集合时清理旧错误和旧文档，成功后展示新集合数据', async () => {
    const store = useKbStore()
    store.currentCollectionId = 'kb-old'
    store.documents = [document]
    store.listStatus = 'error'
    store.errorMessage = '旧错误'
    mockedListDocuments.mockResolvedValueOnce([document])

    const pending = store.select('kb-1')
    expect(store.documents).toEqual([])
    expect(store.listStatus).toBe('loading')
    expect(store.errorMessage).toBeNull()
    await pending
    expect(store.documents).toEqual([document])
    expect(store.listStatus).toBe('success')
  })
})
