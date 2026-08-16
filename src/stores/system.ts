import { defineStore } from 'pinia'
import { listLogs, getTrace, listEvalSets, runEval, getEvalRun, getCost } from '@/api/system'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { CostStat, EvalRun, EvalSet, SystemLog, TraceDetail } from '@/types'

/** 系统 store（docs/02 §7）：只读查询（日志/评估/成本）；后端未实现的分组按 per-feature 降级 */
export const useSystemStore = defineStore('system', {
  state: () => ({
    logs: [] as SystemLog[],
    logTotal: 0,
    evalSets: [] as EvalSet[],
    evalRuns: [] as EvalRun[],
    cost: null as CostStat | null,
    loading: false,
  }),
  getters: {
    /** 后端未实现运行日志接口（HTTP 404 打标） */
    logsUnavailable: () => isUnavailable(FEATURE.systemLogs),
    /** 后端未实现评估接口 */
    evalsUnavailable: () => isUnavailable(FEATURE.systemEvals),
    /** 后端未实现成本接口 */
    costUnavailable: () => isUnavailable(FEATURE.systemCost),
  },
  actions: {
    async listLogs(params: { page?: number; page_size?: number; trace_id?: string; level?: string } = {}) {
      if (this.logsUnavailable) return
      this.loading = true
      try {
        const res = await swallowNotImplemented(listLogs({ page: 1, page_size: 20, ...params }))
        if (res) {
          this.logs = res.items
          this.logTotal = res.total
        }
      } finally {
        this.loading = false
      }
    },
    async trace(traceId: string): Promise<TraceDetail> {
      return getTrace(traceId)
    },
    async listEvals() {
      if (this.evalsUnavailable) return
      const sets = await swallowNotImplemented(listEvalSets())
      if (sets) this.evalSets = sets
    },
    async runEval(evalSetId: string) {
      const run = await runEval(evalSetId)
      return run
    },
    async evalRunDetail(runId: string) {
      return getEvalRun(runId)
    },
    async loadCost() {
      if (this.costUnavailable) return
      const cost = await swallowNotImplemented(getCost())
      if (cost) this.cost = cost
    },
  },
})
