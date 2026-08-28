import { defineStore } from 'pinia'
import { listLogs as fetchLogs, getTrace } from '@/api/system'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { SystemLog, TraceDetail } from '@/types'

type SystemListStatus = 'idle' | 'loading' | 'success-empty' | 'success' | 'error' | 'unavailable'
type LogQuery = { page?: number; page_size?: number; trace_id?: string; level?: string }

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

/** 系统 store（docs/02 §7）：运行日志查询 + trace 全链路；评估/成本契约层已随 UI 精简删除（08-20） */
export const useSystemStore = defineStore('system', {
  state: () => ({
    logs: [] as SystemLog[],
    logTotal: 0,
    loading: false,
    status: 'idle' as SystemListStatus,
    errorMessage: null as string | null,
    lastLogParams: {} as LogQuery,
  }),
  getters: {
    /** 后端未实现运行日志接口（HTTP 404 打标） */
    logsUnavailable: () => isUnavailable(FEATURE.systemLogs),
  },
  actions: {
    async listLogs(params: LogQuery = {}) {
      this.lastLogParams = { ...params }
      if (this.logsUnavailable) {
        this.status = 'unavailable'
        return
      }
      this.loading = true
      this.status = 'loading'
      this.errorMessage = null
      try {
        const res = await swallowNotImplemented(fetchLogs({ page: params.page ?? 1, page_size: params.page_size ?? 20, ...params }))
        if (res) {
          this.logs = res.items
          this.logTotal = res.total
          this.status = res.items.length ? 'success' : 'success-empty'
        } else {
          this.status = 'unavailable'
        }
      } catch (e) {
        this.status = 'error'
        this.errorMessage = messageOf(e, '运行日志加载失败')
      } finally {
        this.loading = false
      }
    },
    async retry() {
      await this.listLogs(this.lastLogParams)
    },
    async trace(traceId: string): Promise<TraceDetail> {
      return getTrace(traceId)
    },
  },
})
