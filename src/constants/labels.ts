import type { CandidateChangeType, CandidateStatus, Role } from '@/types'

/** 角色展示文案（SettingsView / TopBar 共用，单点维护） */
export const ROLE_LABEL: Record<Role, string> = {
  admin: '管理员',
  developer: '开发者',
  viewer: '访客',
}

/** 候选区状态文案（EvolutionManage 筛选/标签，docs/06 §5 闭环） */
export const CANDIDATE_STATUS_LABEL: Record<CandidateStatus, string> = {
  candidate: '候选',
  validating: '验证中',
  approved: '已批准',
  rejected: '已拒绝',
  published: '已发布',
  rolled_back: '已回滚',
}

/** 候选变更载体文案（docs/06 §5.3 更新载体） */
export const CANDIDATE_CHANGE_LABEL: Record<CandidateChangeType, string> = {
  prompt: '提示词',
  skill: '技能',
  tool: '工具',
  memory: '记忆',
  context: '上下文',
}
