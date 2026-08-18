import { defineStore } from 'pinia'
import {
  listCandidates,
  getCandidate,
  validateCandidate,
  publishCandidate,
  rejectCandidate,
  rollbackCandidate,
} from '@/api/evolution'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { Candidate, CandidateStatus } from '@/types'

export type CandidateAction = 'validate' | 'publish' | 'reject' | 'rollback'

/** 经验候选区 store（docs/06 §5 契约提案）：列表 + 状态动作；后端未实现 → FEATURE.evolution 降级 */
export const useEvolutionStore = defineStore('evolution', {
  state: () => ({
    candidates: [] as Candidate[],
    total: 0,
    loading: false,
    /** 当前状态筛选（'all' = 不过滤） */
    statusFilter: 'all' as CandidateStatus | 'all',
    search: '',
  }),
  getters: {
    unavailable: () => isUnavailable(FEATURE.evolution),
  },
  actions: {
    async list() {
      if (this.unavailable) return
      this.loading = true
      try {
        const res = await swallowNotImplemented(
          listCandidates({
            status: this.statusFilter === 'all' ? undefined : this.statusFilter,
            search: this.search.trim() || undefined,
            page: 1,
            page_size: 100,
          }),
        )
        if (res) {
          this.candidates = res.items
          this.total = res.total
        }
      } finally {
        this.loading = false
      }
    },
    async detail(id: string): Promise<Candidate | undefined> {
      if (this.unavailable) return undefined
      return swallowNotImplemented(getCandidate(id))
    },
    /** 状态动作（validate/publish/reject/rollback）成功后保持筛选重查 */
    async runAction(id: string, action: CandidateAction) {
      if (action === 'validate') await validateCandidate(id)
      else if (action === 'publish') await publishCandidate(id)
      else if (action === 'reject') await rejectCandidate(id)
      else await rollbackCandidate(id)
      await this.list()
    },
  },
})
