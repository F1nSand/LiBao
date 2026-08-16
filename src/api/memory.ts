import { httpGet, httpPost, httpDelete } from './http'
import type {
  Paged,
  MemoryTrace,
  LongTermMemory,
  LongTermMemoryVersion,
  CreateLongTermMemoryRequest,
  MemoryMaintenanceResult,
} from '@/types'

export function listTraces(params: { page?: number; page_size?: number; conversation_id?: string } = {}) {
  return httpGet<Paged<MemoryTrace>>('/memory/traces', { params })
}

export function listLongterm() {
  return httpGet<LongTermMemory[]>('/memory/longterm')
}

export function createLongterm(body: CreateLongTermMemoryRequest) {
  return httpPost<LongTermMemory>('/memory/longterm', body)
}

export function listLongtermVersions(id: string) {
  return httpGet<LongTermMemoryVersion[]>(`/memory/longterm/${id}/versions`)
}

export function deleteLongterm(id: string) {
  return httpDelete<null>(`/memory/longterm/${id}`)
}

export function maintenance() {
  return httpPost<MemoryMaintenanceResult>('/memory/maintenance')
}
