import { defineStore } from 'pinia'
import { listLogs, getTrace } from '@/api/system'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { SystemLog, TraceDetail } from '@/types'

/** 系统 store（docs/02 §7）：运行日志查询 + trace 全链路；评估/成本契约层已随 UI 精简删除（08-20） */
export const useSystemStore = defineStore('system', {
  state: () => ({
    logs: [] as SystemLog[],
    logTotal: 0,
    loading: false,
  }),
  getters: {
    /** 后端未实现运行日志接口（HTTP 404 打标） */
    logsUnavailable: () => isUnavailable(FEATURE.systemLogs),
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
  },
})
