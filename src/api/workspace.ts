import { httpGet, httpPost, httpPatch, httpDelete } from './http'
import type { Paged, Workspace, WorkspaceFile, CreateWorkspaceRequest, UpdateWorkspaceRequest } from '@/types'
import type { PageParams } from './chat'

/** 工作区（M7-B 契约，交接板 2026-08-20；docs/03 §5.14） */
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

export function archiveWorkspace(id: string) {
  return httpDelete<null>(`/workspaces/${id}`)
}

/** 打开本地文件夹（OS reveal root_path；交接板 2026-08-21 提案，真实后端未实现时前端降级） */
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

/** 删除文件（目录不支持） */
export function deleteWorkspaceFile(wsId: string, path: string) {
  return httpDelete<null>(`/workspaces/${encodeURIComponent(wsId)}/files`, { params: { path } })
}
