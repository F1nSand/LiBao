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

/** 知识库 store（docs/02 §7）：集合/文档列表 + 索引状态 */
export const useKbStore = defineStore('kb', {
  state: () => ({
    collections: [] as KbCollection[],
    currentCollectionId: null as string | null,
    documents: [] as KbDocument[],
    loading: false,
  }),
  getters: {
    currentCollection: (s) => s.collections.find((c) => c.id === s.currentCollectionId) ?? null,
  },
  actions: {
    async listCollections() {
      this.collections = await listCollections()
      if (!this.currentCollectionId && this.collections.length > 0) {
        this.currentCollectionId = this.collections[0].id
        await this.listDocuments(this.collections[0].id)
      }
    },
    async create(name: string) {
      const c = await createCollection({ name })
      this.collections.unshift(c)
      this.currentCollectionId = c.id
      this.documents = []
    },
    async remove(id: string) {
      await deleteCollection(id)
      this.collections = this.collections.filter((c) => c.id !== id)
      if (this.currentCollectionId === id) {
        this.currentCollectionId = null
        this.documents = []
      }
    },
    async select(id: string) {
      this.currentCollectionId = id
      await this.listDocuments(id)
    },
    async listDocuments(id: string) {
      this.documents = await listDocuments(id)
    },
    async upload(id: string, file: File, onProgress?: (p: number) => void) {
      const d = await uploadDocument(id, file, onProgress)
      this.documents.unshift(d)
      return d
    },
    async status(id: string): Promise<KbDocumentStatusDetail> {
      return getDocumentStatus(id)
    },
    async reindex(id: string) {
      await reindexDocument(id)
      if (this.currentCollectionId) await this.listDocuments(this.currentCollectionId)
    },
    async archive(id: string) {
      await archiveDocument(id)
      if (this.currentCollectionId) await this.listDocuments(this.currentCollectionId)
    },
    async removeDocument(id: string) {
      await deleteDocument(id)
      if (this.currentCollectionId) await this.listDocuments(this.currentCollectionId)
    },
    async search(req: KbSearchRequest): Promise<KbSearchHit[]> {
      return searchKb(req)
    },
  },
})
