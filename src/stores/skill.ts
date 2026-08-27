import { defineStore } from 'pinia'
import { listSkills } from '@/api/skill'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { Skill } from '@/types'

/** Skills 目录 store（M7-A 简化 2026-08-25：只读两级目录——全局 ~/.LiBao/skills + 工作区 .agent/skills） */
export const useSkillStore = defineStore('skill', {
  state: () => ({
    global: [] as Skill[],
    workspace: [] as Skill[],
    loading: false,
  }),
  getters: {
    unavailable: () => isUnavailable(FEATURE.skills),
  },
  actions: {
    async listGlobal() {
      if (this.unavailable) return
      this.loading = true
      try {
        const res = await swallowNotImplemented(listSkills())
        if (res) this.global = res
      } finally {
        this.loading = false
      }
    },
    async listWorkspace(workspaceId: string) {
      if (this.unavailable) return
      this.loading = true
      try {
        const res = await swallowNotImplemented(listSkills({ workspace_id: workspaceId }))
        if (res) this.workspace = res
      } finally {
        this.loading = false
      }
    },
  },
})
