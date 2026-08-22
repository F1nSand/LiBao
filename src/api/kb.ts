import { httpGet, httpPost, httpPatch, httpDelete } from './http'
import type { AxiosProgressEvent } from 'axios'
import type {
  KbCollection,
  KbDocument,
  KbDocumentStatusDetail,
  KbSearchHit,
  KbSearchRequest,
} from '@/types'

export function listCollections() {
  return httpGet<KbCollection[]>('/kb/collections')
}

export function createCollection(body: { name: string; chunk_size?: number; overlap?: number }) {
  return httpPost<KbCollection>('/kb/collections', body)
}

export function deleteCollection(id: string) {
  return httpDelete<null>(`/kb/collections/${id}`)
}

export function listDocuments(collectionId: string) {
  return httpGet<KbDocument[]>(`/kb/collections/${collectionId}/documents`)
}

export function uploadDocument(collectionId: string, file: File, onProgress?: (p: number) => void) {
  const form = new FormData()
  form.append('file', file)
  return httpPost<KbDocument>(`/kb/collections/${collectionId}/documents`, form, {
    onUploadProgress: (e: AxiosProgressEvent) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
}

export function getDocumentStatus(id: string) {
  return httpGet<KbDocumentStatusDetail>(`/kb/documents/${id}/status`)
}

export function reindexDocument(id: string) {
  return httpPost<KbDocument>(`/kb/documents/${id}/reindex`)
}

export function archiveDocument(id: string) {
  return httpPatch<KbDocument>(`/kb/documents/${id}/status`, { status: 'archived' })
}

export function deleteDocument(id: string) {
  return httpDelete<null>(`/kb/documents/${id}`)
}

export function searchKb(body: KbSearchRequest) {
  return httpPost<KbSearchHit[]>('/kb/search', body)
}
