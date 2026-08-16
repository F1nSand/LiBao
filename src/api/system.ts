import { httpGet, httpPost, httpPatch } from './http'
import type {
  Paged,
  SystemLog,
  TraceDetail,
  EvalSet,
  EvalCase,
  EvalRun,
  EvalCaseResult,
  CostStat,
} from '@/types'

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

export function listEvalSets() {
  return httpGet<EvalSet[]>('/system/evals/sets')
}

export function createEvalSet(body: { name: string; description?: string }) {
  return httpPost<EvalSet>('/system/evals/sets', body)
}

export function addEvalCase(evalSetId: string, body: { input: string; expected: string }) {
  return httpPost<EvalCase>(`/system/evals/sets/${evalSetId}/cases`, body)
}

export function patchEvalCase(evalSetId: string, caseId: string, body: { active: boolean }) {
  return httpPatch<EvalCase>(`/system/evals/sets/${evalSetId}/cases/${caseId}`, body)
}

export function runEval(evalSetId: string) {
  return httpPost<EvalRun>('/system/evals/run', { eval_set_id: evalSetId })
}

export function listEvalRuns() {
  return httpGet<EvalRun[]>('/system/evals/runs')
}

export function getEvalRun(runId: string) {
  return httpGet<{ run: EvalRun; results: EvalCaseResult[] }>(`/system/evals/runs/${runId}`)
}

export function getCost(params: { start?: string; end?: string; provider?: string } = {}) {
  return httpGet<CostStat>('/system/cost', { params })
}
