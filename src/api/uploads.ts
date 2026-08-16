import { httpGet, httpDelete } from './http'
import { httpPost } from './http'
import type { AxiosProgressEvent } from 'axios'
import type { UploadResponse, Attachment, AttachmentAnalysis } from '@/types'

export function uploadAttachment(
  file: File,
  onProgress?: (p: number) => void,
  signal?: AbortSignal,
) {
  const form = new FormData()
  form.append('file', file)
  return httpPost<UploadResponse>('/uploads', form, {
    onUploadProgress: (e: AxiosProgressEvent) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
    signal,
  })
}

export function getAttachment(id: string) {
  return httpGet<Attachment>(`/attachments/${id}`)
}

export function getAttachmentAnalysis(id: string) {
  return httpGet<AttachmentAnalysis>(`/attachments/${id}/analysis`)
}

export function deleteAttachment(id: string) {
  return httpDelete<null>(`/attachments/${id}`)
}
