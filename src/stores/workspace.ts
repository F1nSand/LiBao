import { defineStore } from 'pinia'
import { listWorkspaces, createWorkspace, updateWorkspace, deleteWorkspace } from '@/api/workspace'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { CreateWorkspaceRequest, UpdateWorkspaceRequest, Workspace } from '@/types'

/** 工作区 store（M7-B，docs/02 §7）：气泡列表 + 创建/编辑/删除；文件树与工作区会话走 api 直调，不进 store */
export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    workspaces: [] as Workspace[],
    loading: false,
    status: 'idle' as 'idle' | 'loading' | 'success' | 'error' | 'unavailable',
    errorMessage: null as string | null,
  }),
  getters: {
    unavailable: () => isUnavailable(FEATURE.workspaces),
  },
  actions: {
    async list() {
      if (this.unavailable) {
        this.status = 'unavailable'
        return
      }
      this.loading = true
      this.status = 'loading'
      this.errorMessage = null
      try {
        const res = await swallowNotImplemented(listWorkspaces({ page_size: 100 }))
        if (res) {
          this.workspaces = res.items
          this.status = 'success'
        } else {
          this.status = 'unavailable'
        }
      } catch (e) {
        this.status = 'error'
        this.errorMessage = e instanceof Error ? e.message : '工作区加载失败'
      } finally {
        this.loading = false
      }
    },
    async retry() {
      await this.list()
    },
    async create(body: CreateWorkspaceRequest) {
      if (this.unavailable) return
      await createWorkspace(body)
      await this.list()
    },
    async update(id: string, body: UpdateWorkspaceRequest) {
      if (this.unavailable) return
      await updateWorkspace(id, body)
      await this.list()
    },
    async remove(id: string) {
      if (this.unavailable) return
      await deleteWorkspace(id)
      await this.list()
    },
  },
})
