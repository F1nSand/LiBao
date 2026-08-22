import { defineStore } from 'pinia'
import {
  listLongterm,
  createLongterm,
  listLongtermVersions,
  deleteLongterm,
  maintenance,
} from '@/api/memory'
import type {
  CreateLongTermMemoryRequest,
  LongTermMemory,
  LongTermMemoryVersion,
  MemoryMaintenanceResult,
} from '@/types'

/** 记忆 store（docs/02 §7）：长期记忆（只增版本化）+ maintenance 整理 */
export const useMemoryStore = defineStore('memory', {
  state: () => ({
    longterm: [] as LongTermMemory[],
    loading: false,
  }),
  actions: {
    async listLongterm() {
      this.longterm = await listLongterm()
    },
    async create(body: CreateLongTermMemoryRequest) {
      const m = await createLongterm(body)
      this.longterm.unshift(m)
      return m
    },
    async versions(id: string): Promise<LongTermMemoryVersion[]> {
      return listLongtermVersions(id)
    },
    async remove(id: string) {
      await deleteLongterm(id)
      this.longterm = this.longterm.filter((m) => m.id !== id)
    },
    async maintenance(): Promise<MemoryMaintenanceResult> {
      const res = await maintenance()
      await this.listLongterm()
      return res
    },
  },
})
