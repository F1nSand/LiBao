import { httpGet } from './http'
import type { Paged, SystemLog, TraceDetail } from '@/types'

export function listLogs(params: {
  page?: number
  page_size?: number
  trace_id?: string
  level?: string
  start?: string
  end?: string
} = {}) {
  return httpGet<Paged<SystemLog>>('/system/logs', { params })
}

export function getTrace(traceId: string) {
  return httpGet<TraceDetail>(`/system/logs/trace/${traceId}`)
}
