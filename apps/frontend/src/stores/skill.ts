import { defineStore } from 'pinia'
import { listSkills } from '@/api/skill'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { Skill } from '@/types'

type SkillStatus = 'idle' | 'loading' | 'success-empty' | 'success' | 'error' | 'unavailable'

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

/** Skills 目录 store（M7-A 简化 2026-08-25：只读两级目录——全局 ~/.LiBao/skills + 工作区 .agent/skills） */
export const useSkillStore = defineStore('skill', {
  state: () => ({
    global: [] as Skill[],
    workspace: [] as Skill[],
    loading: false,
    globalStatus: 'idle' as SkillStatus,
    workspaceStatus: 'idle' as SkillStatus,
    globalErrorMessage: null as string | null,
    workspaceErrorMessage: null as string | null,
  }),
  getters: {
    unavailable: () => isUnavailable(FEATURE.skills),
  },
  actions: {
    async listGlobal() {
      if (this.unavailable) {
        this.globalStatus = 'unavailable'
        return
      }
      this.loading = true
      this.globalStatus = 'loading'
      this.globalErrorMessage = null
      try {
        const res = await swallowNotImplemented(listSkills())
        if (res) {
          this.global = res
          this.globalStatus = res.length ? 'success' : 'success-empty'
        } else {
          this.globalStatus = 'unavailable'
        }
      } catch (e) {
        this.globalStatus = 'error'
        this.globalErrorMessage = messageOf(e, '全局 Skills 加载失败')
      } finally {
        this.loading = false
      }
    },
    async retryGlobal() {
      await this.listGlobal()
    },
    async listWorkspace(workspaceId: string) {
      if (this.unavailable) {
        this.workspaceStatus = 'unavailable'
        return
      }
      this.loading = true
      this.workspaceStatus = 'loading'
      this.workspaceErrorMessage = null
      try {
        const res = await swallowNotImplemented(listSkills({ workspace_id: workspaceId }))
        if (res) {
          this.workspace = res
          this.workspaceStatus = res.length ? 'success' : 'success-empty'
        } else {
          this.workspaceStatus = 'unavailable'
        }
      } catch (e) {
        this.workspaceStatus = 'error'
        this.workspaceErrorMessage = messageOf(e, '工作区 Skills 加载失败')
      } finally {
        this.loading = false
      }
    },
    async retryWorkspace(workspaceId: string) {
      await this.listWorkspace(workspaceId)
    },
  },
})
