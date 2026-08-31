import { httpGet, httpPost, httpPatch, httpDelete } from './http'
import type { Paged, Workspace, WorkspaceFile, CreateWorkspaceRequest, UpdateWorkspaceRequest } from '@/types'
import type { PageParams } from './chat'

/** 工作区（M7-B 契约，交接板 2026-08-20；《02》接口契约 §5.14） */
export function listWorkspaces(params: PageParams = {}) {
  return httpGet<Paged<Workspace>>('/workspaces', { params })
}

export function getWorkspace(id: string) {
  return httpGet<Workspace>(`/workspaces/${id}`)
}

export function createWorkspace(body: CreateWorkspaceRequest) {
  return httpPost<Workspace>('/workspaces', body)
}

export function updateWorkspace(id: string, body: UpdateWorkspaceRequest) {
  return httpPatch<Workspace>(`/workspaces/${id}`, body)
}

/** 删除工作区（硬删：本地目录 + DB 行 + 级联对话/记忆/文件；交接板 2026-08-21，后端 DELETE 由软删改硬删） */
export function deleteWorkspace(id: string) {
  return httpDelete<null>(`/workspaces/${encodeURIComponent(id)}`)
}

/** 打开本地文件夹（OS reveal root_path；交接板 2026-08-21 契约，后端已实现 2f5c9e5） */
export function revealWorkspace(id: string) {
  return httpPost<null>(`/workspaces/${encodeURIComponent(id)}/reveal`)
}

/** 文件：列目录（path 相对 root；空 = 顶层） */
export function listWorkspaceFiles(wsId: string, path = '') {
  return httpGet<WorkspaceFile[]>(`/workspaces/${encodeURIComponent(wsId)}/files`, { params: { path } })
}

/** 读文件内容（限 50K） */
export function readWorkspaceFile(wsId: string, path: string) {
  return httpGet<{ path: string; content: string }>(`/workspaces/${encodeURIComponent(wsId)}/files/content`, {
    params: { path },
  })
}

/** 写/创建文件（幂等 upsert） */
export function writeWorkspaceFile(wsId: string, body: { path: string; content: string }) {
  return httpPost<WorkspaceFile>(`/workspaces/${encodeURIComponent(wsId)}/files`, body)
}

/** 删除文件（目录：递归删子项，交接板 2026-08-21） */
export function deleteWorkspaceFile(wsId: string, path: string) {
  return httpDelete<null>(`/workspaces/${encodeURIComponent(wsId)}/files`, { params: { path } })
}

/** 重命名文件/文件夹（子项前缀由服务端同步；交接板 2026-08-21 契约，后端已实现 08-22，降级保留为安全网） */
export function renameWorkspaceFile(wsId: string, body: { old_path: string; new_path: string }) {
  return httpPatch<null>(`/workspaces/${encodeURIComponent(wsId)}/files/rename`, body)
}

/** 新建文件夹（path 相对 root；交接板 2026-08-21 契约，后端已实现 08-22，降级保留为安全网） */
export function createWorkspaceDir(wsId: string, path: string) {
  return httpPost<WorkspaceFile>(`/workspaces/${encodeURIComponent(wsId)}/files`, { path, is_dir: true })
}
