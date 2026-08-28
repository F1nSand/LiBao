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

type MemoryListStatus = 'idle' | 'loading' | 'success-empty' | 'success' | 'error'

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

/** 记忆 store（docs/02 §7）：长期记忆（只增版本化）+ maintenance 整理 */
export const useMemoryStore = defineStore('memory', {
  state: () => ({
    longterm: [] as LongTermMemory[],
    loading: false,
    status: 'idle' as MemoryListStatus,
    errorMessage: null as string | null,
  }),
  actions: {
    async listLongterm() {
      this.loading = true
      this.status = 'loading'
      this.errorMessage = null
      try {
        this.longterm = await listLongterm()
        this.status = this.longterm.length ? 'success' : 'success-empty'
      } catch (e) {
        this.status = 'error'
        this.errorMessage = messageOf(e, '长期记忆加载失败')
      } finally {
        this.loading = false
      }
    },
    async retry() {
      await this.listLongterm()
    },
    async create(body: CreateLongTermMemoryRequest) {
      try {
        const m = await createLongterm(body)
        this.longterm.unshift(m)
        this.status = 'success'
        this.errorMessage = null
        return m
      } catch (e) {
        this.status = 'error'
        this.errorMessage = messageOf(e, '记忆创建失败')
        throw e
      }
    },
    async versions(id: string): Promise<LongTermMemoryVersion[]> {
      return listLongtermVersions(id)
    },
    async remove(id: string) {
      try {
        await deleteLongterm(id)
        this.longterm = this.longterm.filter((m) => m.id !== id)
        this.status = this.longterm.length ? 'success' : 'success-empty'
        this.errorMessage = null
      } catch (e) {
        this.status = 'error'
        this.errorMessage = messageOf(e, '记忆删除失败')
        throw e
      }
    },
    async maintenance(): Promise<MemoryMaintenanceResult> {
      try {
        const res = await maintenance()
        await this.listLongterm()
        return res
      } catch (e) {
        this.status = 'error'
        this.errorMessage = messageOf(e, '记忆整理失败')
        throw e
      }
    },
  },
})
