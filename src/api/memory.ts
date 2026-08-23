import { httpGet, httpPost, httpDelete, httpPut } from './http'
import type {
  LongTermMemory,
  LongTermMemoryVersion,
  CreateLongTermMemoryRequest,
  MemoryMaintenanceResult,
  ProjectMemoryFile,
} from '@/types'

export function listLongterm() {
  return httpGet<LongTermMemory[]>('/memory/longterm')
}

export function createLongterm(body: CreateLongTermMemoryRequest) {
  return httpPost<LongTermMemory>('/memory/longterm', body)
}

export function updateLongterm(id: string, body: { body: unknown; importance?: number }) {
  return httpPut<LongTermMemory>(`/memory/longterm/${id}`, body)
}

/** 项目记忆文件索引（P5：工作区 .agent/memory/*.md；正文按需 readWorkspaceFile） */
export function listProjectMemory(workspaceId: string) {
  return httpGet<ProjectMemoryFile[]>('/memory/project', { params: { workspace_id: workspaceId } })
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
