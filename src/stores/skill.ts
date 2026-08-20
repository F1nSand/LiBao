import { defineStore } from 'pinia'
import { listSkills, createSkill, importSkill, updateSkill, deleteSkill } from '@/api/skill'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { CreateSkillRequest, Skill } from '@/types'

/** Skills 管理 store（M7-A 契约，交接板 2026-08-20；与工具同模式、默认关闭、developer+；后端未实现 → FEATURE.skills 降级） */
export const useSkillStore = defineStore('skill', {
  state: () => ({
    skills: [] as Skill[],
    loading: false,
  }),
  getters: {
    unavailable: () => isUnavailable(FEATURE.skills),
  },
  actions: {
    async list() {
      if (this.unavailable) return
      this.loading = true
      try {
        const res = await swallowNotImplemented(listSkills({ page_size: 100 }))
        if (res) this.skills = res.items
      } finally {
        this.loading = false
      }
    },
    async toggle(id: string, enabled: boolean) {
      if (this.unavailable) return
      await updateSkill(id, { enabled })
      await this.list()
    },
    async create(body: CreateSkillRequest) {
      if (this.unavailable) return
      await createSkill(body)
      await this.list()
    },
    async importFromGit(url: string) {
      if (this.unavailable) return
      await importSkill({ url })
      await this.list()
    },
    async remove(id: string) {
      if (this.unavailable) return
      await deleteSkill(id)
      await this.list()
    },
  },
})
