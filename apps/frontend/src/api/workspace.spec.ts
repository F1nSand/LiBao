import { describe, it, expect, vi, beforeEach } from 'vitest'
import { httpGet, httpPost, httpPatch, httpDelete } from './http'
import {
  listWorkspaces,
  getWorkspace,
  createWorkspace,
  updateWorkspace,
  deleteWorkspace,
  revealWorkspace,
  listWorkspaceFiles,
  readWorkspaceFile,
  writeWorkspaceFile,
  deleteWorkspaceFile,
  renameWorkspaceFile,
  createWorkspaceDir,
} from './workspace'

vi.mock('./http', () => ({
  httpGet: vi.fn(),
  httpPost: vi.fn(),
  httpPatch: vi.fn(),
  httpDelete: vi.fn(),
}))

const mockedGet = vi.mocked(httpGet)
const mockedPost = vi.mocked(httpPost)
const mockedPatch = vi.mocked(httpPatch)
const mockedDelete = vi.mocked(httpDelete)

describe('api/workspace（M7-B 契约，交接板 2026-08-20）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('listWorkspaces 透传分页', () => {
    listWorkspaces({ page: 2, page_size: 20 })
    expect(mockedGet).toHaveBeenCalledWith('/workspaces', { params: { page: 2, page_size: 20 } })
  })

  it('getWorkspace 命中 /:id', () => {
    getWorkspace('ws_001')
    expect(mockedGet).toHaveBeenCalledWith('/workspaces/ws_001')
  })

  it('createWorkspace POST body', () => {
    createWorkspace({ name: 'n', description: 'd', project_instructions: 'f' })
    expect(mockedPost).toHaveBeenCalledWith('/workspaces', { name: 'n', description: 'd', project_instructions: 'f' })
  })

  it('updateWorkspace PATCH /:id', () => {
    updateWorkspace('ws_001', { name: 'x' })
    expect(mockedPatch).toHaveBeenCalledWith('/workspaces/ws_001', { name: 'x' })
  })

  it('deleteWorkspace DELETE /:id（路径 encodeURIComponent）', () => {
    deleteWorkspace('ws_001')
    expect(mockedDelete).toHaveBeenCalledWith('/workspaces/ws_001')
  })

  it('revealWorkspace POST /:id/reveal（路径 encodeURIComponent）', () => {
    revealWorkspace('ws_001')
    expect(mockedPost).toHaveBeenCalledWith('/workspaces/ws_001/reveal')
  })

  it('listWorkspaceFiles 带 path 参数（路径 encodeURIComponent）', () => {
    listWorkspaceFiles('ws_001', 'docs')
    expect(mockedGet).toHaveBeenCalledWith('/workspaces/ws_001/files', { params: { path: 'docs' } })
  })

  it('listWorkspaceFiles 空 path 默认顶层', () => {
    listWorkspaceFiles('ws_001')
    expect(mockedGet).toHaveBeenCalledWith('/workspaces/ws_001/files', { params: { path: '' } })
  })

  it('readWorkspaceFile 命中 content 端点', () => {
    readWorkspaceFile('ws_001', 'README.md')
    expect(mockedGet).toHaveBeenCalledWith('/workspaces/ws_001/files/content', { params: { path: 'README.md' } })
  })

  it('writeWorkspaceFile POST 文件', () => {
    writeWorkspaceFile('ws_001', { path: 'a.md', content: 'hi' })
    expect(mockedPost).toHaveBeenCalledWith('/workspaces/ws_001/files', { path: 'a.md', content: 'hi' })
  })

  it('deleteWorkspaceFile DELETE 带 path', () => {
    deleteWorkspaceFile('ws_001', 'a.md')
    expect(mockedDelete).toHaveBeenCalledWith('/workspaces/ws_001/files', { params: { path: 'a.md' } })
  })

  it('renameWorkspaceFile PATCH files/rename（old_path→new_path）', () => {
    renameWorkspaceFile('ws_001', { old_path: 'a.md', new_path: 'b.md' })
    expect(mockedPatch).toHaveBeenCalledWith('/workspaces/ws_001/files/rename', { old_path: 'a.md', new_path: 'b.md' })
  })

  it('createWorkspaceDir POST files 带 is_dir', () => {
    createWorkspaceDir('ws_001', 'docs/assets')
    expect(mockedPost).toHaveBeenCalledWith('/workspaces/ws_001/files', { path: 'docs/assets', is_dir: true })
  })
})
