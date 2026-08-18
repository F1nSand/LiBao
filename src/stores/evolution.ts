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

/** 动作 → API 映射（闭环联合类型穷举；漏加 key 即编译错误，避免静默误路由） */
const ACTION_API: Record<CandidateAction, (id: string) => Promise<Candidate>> = {
  validate: validateCandidate,
  publish: publishCandidate,
  reject: rejectCandidate,
  rollback: rollbackCandidate,
}

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
      await ACTION_API[action](id)
      await this.list()
    },
  },
})
