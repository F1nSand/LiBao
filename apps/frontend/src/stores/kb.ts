import { defineStore } from 'pinia'
import {
  listCollections,
  createCollection,
  deleteCollection,
  listDocuments,
  uploadDocument,
  getDocumentStatus,
  reindexDocument,
  archiveDocument,
  deleteDocument,
  searchKb,
} from '@/api/kb'
import type {
  KbCollection,
  KbDocument,
  KbDocumentStatusDetail,
  KbSearchHit,
  KbSearchRequest,
} from '@/types'

type KbListStatus = 'idle' | 'loading' | 'success-empty' | 'success' | 'error'
type KbListTarget = 'collections' | 'documents'

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

/** 知识库 store（《02》前端设计 §7）：集合/文档列表 + 索引状态 */
export const useKbStore = defineStore('kb', {
  state: () => ({
    collections: [] as KbCollection[],
    currentCollectionId: null as string | null,
    documents: [] as KbDocument[],
    loading: false,
    listStatus: 'idle' as KbListStatus,
    errorMessage: null as string | null,
    lastList: null as KbListTarget | null,
  }),
  getters: {
    currentCollection: (s) => s.collections.find((c) => c.id === s.currentCollectionId) ?? null,
  },
  actions: {
    async listCollections() {
      this.loading = true
      this.listStatus = 'loading'
      this.errorMessage = null
      this.lastList = 'collections'
      try {
        const collections = await listCollections()
        this.collections = collections
        if (this.currentCollectionId && !this.collections.some((c) => c.id === this.currentCollectionId)) {
          this.currentCollectionId = null
          this.documents = []
        }
        if (!this.currentCollectionId && this.collections.length > 0) {
          this.currentCollectionId = this.collections[0].id
          await this.listDocuments(this.collections[0].id)
        } else {
          this.listStatus = this.collections.length ? 'success' : 'success-empty'
        }
      } catch (e) {
        this.listStatus = 'error'
        this.errorMessage = messageOf(e, '知识库集合加载失败')
      } finally {
        this.loading = false
      }
    },
    async retry() {
      if (this.lastList === 'documents' && this.currentCollectionId) {
        await this.listDocuments(this.currentCollectionId)
      } else {
        await this.listCollections()
      }
    },
    async create(name: string) {
      try {
        const c = await createCollection({ name })
        this.collections.unshift(c)
        this.currentCollectionId = c.id
        this.documents = []
        this.listStatus = 'success'
        this.errorMessage = null
      } catch (e) {
        this.listStatus = 'error'
        this.errorMessage = messageOf(e, '集合创建失败')
        throw e
      }
    },
    async remove(id: string) {
      try {
        await deleteCollection(id)
        this.collections = this.collections.filter((c) => c.id !== id)
        if (this.currentCollectionId === id) {
          this.currentCollectionId = null
          this.documents = []
        }
        this.listStatus = this.collections.length ? 'success' : 'success-empty'
        this.errorMessage = null
      } catch (e) {
        this.listStatus = 'error'
        this.errorMessage = messageOf(e, '集合删除失败')
        throw e
      }
    },
    async select(id: string) {
      this.currentCollectionId = id
      this.documents = []
      await this.listDocuments(id)
    },
    async listDocuments(id: string) {
      this.loading = true
      this.listStatus = 'loading'
      this.errorMessage = null
      this.lastList = 'documents'
      try {
        this.documents = await listDocuments(id)
        this.listStatus = this.documents.length ? 'success' : 'success-empty'
      } catch (e) {
        this.listStatus = 'error'
        this.errorMessage = messageOf(e, '文档列表加载失败')
      } finally {
        this.loading = false
      }
    },
    async upload(id: string, file: File, onProgress?: (p: number) => void) {
      try {
        const d = await uploadDocument(id, file, onProgress)
        this.documents.unshift(d)
        this.listStatus = 'success'
        this.errorMessage = null
        return d
      } catch (e) {
        this.listStatus = 'error'
        this.errorMessage = messageOf(e, '文档上传失败')
        throw e
      }
    },
    async status(id: string): Promise<KbDocumentStatusDetail> {
      return getDocumentStatus(id)
    },
    async reindex(id: string) {
      try {
        await reindexDocument(id)
        if (this.currentCollectionId) await this.listDocuments(this.currentCollectionId)
      } catch (e) {
        this.listStatus = 'error'
        this.errorMessage = messageOf(e, '文档重索引失败')
        throw e
      }
    },
    async archive(id: string) {
      try {
        await archiveDocument(id)
        if (this.currentCollectionId) await this.listDocuments(this.currentCollectionId)
      } catch (e) {
        this.listStatus = 'error'
        this.errorMessage = messageOf(e, '文档下线失败')
        throw e
      }
    },
    async removeDocument(id: string) {
      try {
        await deleteDocument(id)
        if (this.currentCollectionId) await this.listDocuments(this.currentCollectionId)
      } catch (e) {
        this.listStatus = 'error'
        this.errorMessage = messageOf(e, '文档删除失败')
        throw e
      }
    },
    /** 轮询回写行级 live 状态（ChunkStatus status-change），使状态/分块数/操作同源实时收敛 */
    patchDocument(id: string, patch: Partial<Pick<KbDocument, 'status' | 'chunk_count' | 'progress' | 'error'>>) {
      this.documents = this.documents.map((d) => (d.id === id ? { ...d, ...patch } : d))
    },
    async search(req: KbSearchRequest): Promise<KbSearchHit[]> {
      return searchKb(req)
    },
  },
})
