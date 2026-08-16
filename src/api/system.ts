import { httpGet, httpPost, httpPatch, httpPut, httpDelete } from './http'
import type {
  Paged,
  SystemLog,
  TraceDetail,
  EvalSet,
  EvalCase,
  EvalRun,
  EvalCaseResult,
  PairwiseDetail,
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

/** ---------- 评估（docs 03 §5.8 / docs 06 §2.4） ---------- */
export function listEvalSets() {
  return httpGet<EvalSet[]>('/system/evals/sets')
}

export function createEvalSet(body: { name: string; description?: string }) {
  return httpPost<EvalSet>('/system/evals/sets', body)
}

export function updateEvalSet(evalSetId: string, body: { name?: string; description?: string }) {
  return httpPut<EvalSet>(`/system/evals/sets/${evalSetId}`, body)
}

export function deleteEvalSet(evalSetId: string) {
  return httpDelete<null>(`/system/evals/sets/${evalSetId}`)
}

export function listEvalCases(evalSetId: string) {
  return httpGet<EvalCase[]>(`/system/evals/sets/${evalSetId}/cases`)
}

export function addEvalCase(evalSetId: string, body: { input: string; expected: string; layer?: string }) {
  return httpPost<EvalCase>(`/system/evals/sets/${evalSetId}/cases`, body)
}

export function patchEvalCase(
  evalSetId: string,
  caseId: string,
  body: { active?: boolean; input?: string; expected?: string; layer?: string },
) {
  return httpPatch<EvalCase>(`/system/evals/sets/${evalSetId}/cases/${caseId}`, body)
}

export function deleteEvalCase(evalSetId: string, caseId: string) {
  return httpDelete<null>(`/system/evals/sets/${evalSetId}/cases/${caseId}`)
}

export function runEval(evalSetId: string, baselineRunId?: string | null) {
  return httpPost<EvalRun>('/system/evals/run', { eval_set_id: evalSetId, baseline_run_id: baselineRunId ?? undefined })
}

export function listEvalRuns() {
  return httpGet<EvalRun[]>('/system/evals/runs')
}

export function getEvalRun(runId: string) {
  return httpGet<{ run: EvalRun; results: EvalCaseResult[] }>(`/system/evals/runs/${runId}`)
}

export function getPairwise(runId: string, baselineRunId: string) {
  return httpGet<PairwiseDetail>(`/system/evals/runs/${runId}/pairwise`, { params: { baseline_run_id: baselineRunId } })
}

export function getCost(params: { start?: string; end?: string; provider?: string } = {}) {
  return httpGet<CostStat>('/system/cost', { params })
}
