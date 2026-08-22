import { httpGet, httpPost } from './http'
import type { Candidate, CandidateStatus, Paged } from '@/types'

/**
 * 经验候选区（docs/06 §5 契约，后端已实现 08-18）：候选 → 验证 → 批准 → 发布 → 回滚。
 * availability 降级仅兜底。
 */
export function listCandidates(params: {
  status?: CandidateStatus
  search?: string
  page?: number
  page_size?: number
} = {}) {
  return httpGet<Paged<Candidate>>('/evolution/candidates', { params })
}

export function getCandidate(id: string) {
  return httpGet<Candidate>(`/evolution/candidates/${id}`)
}

export function validateCandidate(id: string) {
  return httpPost<Candidate>(`/evolution/candidates/${id}/validate`)
}

export function publishCandidate(id: string) {
  return httpPost<Candidate>(`/evolution/candidates/${id}/publish`)
}

export function rejectCandidate(id: string) {
  return httpPost<Candidate>(`/evolution/candidates/${id}/reject`)
}

export function rollbackCandidate(id: string) {
  return httpPost<Candidate>(`/evolution/candidates/${id}/rollback`)
}
