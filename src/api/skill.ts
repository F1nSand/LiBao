import { httpGet, httpPost, httpPatch, httpDelete } from './http'
import type { Paged, Skill, CreateSkillRequest, ImportSkillRequest } from '@/types'

/** Skills 管理（M7-A 契约，交接板 2026-08-20；docs/03 §5.15） */
export function listSkills(params: { page?: number; page_size?: number } = {}) {
  return httpGet<Paged<Skill>>('/skills', { params })
}

export function getSkill(id: string) {
  return httpGet<Skill>(`/skills/${id}`)
}

export function createSkill(body: CreateSkillRequest) {
  return httpPost<Skill>('/skills', body)
}

export function importSkill(body: ImportSkillRequest) {
  return httpPost<Skill>('/skills/import', body)
}

export function updateSkill(id: string, body: Partial<CreateSkillRequest> & { enabled?: boolean }) {
  return httpPatch<Skill>(`/skills/${id}`, body)
}

export function deleteSkill(id: string) {
  return httpDelete<null>(`/skills/${id}`)
}
