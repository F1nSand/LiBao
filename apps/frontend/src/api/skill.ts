import { httpGet } from './http'
import type { Skill } from '@/types'

/** Skills 目录展示（M7-A 简化 2026-08-25：只读两级目录，删 org CRUD / git 导入） */
export function listSkills(params: { workspace_id?: string } = {}) {
  return httpGet<Skill[]>('/skills', { params })
}
