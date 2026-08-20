import { defineStore } from 'pinia'
import { listWorkspaces, createWorkspace, updateWorkspace, archiveWorkspace } from '@/api/workspace'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { CreateWorkspaceRequest, UpdateWorkspaceRequest, Workspace } from '@/types'

/** 工作区 store（M7-B，docs/02 §7）：气泡列表 + 创建/编辑/归档；文件树与工作区会话走 api 直调，不进 store */
export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    workspaces: [] as Workspace[],
    loading: false,
  }),
  getters: {
    unavailable: () => isUnavailable(FEATURE.workspaces),
  },
  actions: {
    async list() {
      if (this.unavailable) return
      this.loading = true
      try {
        const res = await swallowNotImplemented(listWorkspaces({ page_size: 100 }))
        if (res) this.workspaces = res.items
      } finally {
        this.loading = false
      }
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
    async archive(id: string) {
      if (this.unavailable) return
      await archiveWorkspace(id)
      await this.list()
    },
  },
})
