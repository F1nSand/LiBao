import { defineStore } from 'pinia'
import {
  listLogs,
  getTrace,
  listEvalSets,
  createEvalSet,
  updateEvalSet,
  deleteEvalSet,
  listEvalCases,
  addEvalCase,
  patchEvalCase,
  deleteEvalCase,
  runEval,
  listEvalRuns,
  getEvalRun,
  getPairwise,
  getCost,
} from '@/api/system'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { CostStat, EvalCase, EvalRun, EvalSet, PairwiseDetail, SystemLog, TraceDetail } from '@/types'

/** 系统 store（docs/02 §7）：日志/评估/成本查询 + 评估管理（集/用例/运行/配对）；后端未实现的分组按 per-feature 降级 */
export const useSystemStore = defineStore('system', {
  state: () => ({
    logs: [] as SystemLog[],
    logTotal: 0,
    evalSets: [] as EvalSet[],
    evalCases: [] as EvalCase[],
    evalRuns: [] as EvalRun[],
    pairwise: null as PairwiseDetail | null,
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

    /* ---------- 评估集 ---------- */
    async listEvals() {
      if (this.evalsUnavailable) return
      const sets = await swallowNotImplemented(listEvalSets())
      if (sets) this.evalSets = sets
    },
    async createSet(body: { name: string; description?: string }) {
      await createEvalSet(body)
      await this.listEvals()
    },
    async updateSet(evalSetId: string, body: { name?: string; description?: string }) {
      await updateEvalSet(evalSetId, body)
      await this.listEvals()
    },
    async removeSet(evalSetId: string) {
      await deleteEvalSet(evalSetId)
      this.evalCases = []
      await this.listEvals()
    },

    /* ---------- 用例 ---------- */
    async loadEvalCases(evalSetId: string) {
      const cases = await swallowNotImplemented(listEvalCases(evalSetId))
      if (cases) this.evalCases = cases
    },
    async addCase(evalSetId: string, body: { input: string; expected: string; layer?: string }) {
      await addEvalCase(evalSetId, body)
      await this.loadEvalCases(evalSetId)
    },
    async toggleCase(evalSetId: string, caseId: string, active: boolean) {
      await patchEvalCase(evalSetId, caseId, { active })
      await this.loadEvalCases(evalSetId)
    },
    async removeCase(evalSetId: string, caseId: string) {
      await deleteEvalCase(evalSetId, caseId)
      await this.loadEvalCases(evalSetId)
    },

    /* ---------- 运行 / 配对 ---------- */
    async runEval(evalSetId: string, baselineRunId?: string | null) {
      const run = await runEval(evalSetId, baselineRunId)
      return run
    },
    async evalRunDetail(runId: string) {
      return getEvalRun(runId)
    },
    async loadEvalRuns() {
      const runs = await swallowNotImplemented(listEvalRuns())
      if (runs) this.evalRuns = runs
    },
    async loadPairwise(runId: string, baselineRunId: string) {
      const pairwise = await swallowNotImplemented(getPairwise(runId, baselineRunId))
      if (pairwise) this.pairwise = pairwise
    },

    /* ---------- 成本 ---------- */
    async loadCost() {
      if (this.costUnavailable) return
      const cost = await swallowNotImplemented(getCost())
      if (cost) this.cost = cost
    },
  },
})
