import type { Role } from '@/types'

/** 角色展示文案（SettingsView / TopBar 共用，单点维护） */
export const ROLE_LABEL: Record<Role, string> = {
  admin: '管理员',
  developer: '开发者',
  viewer: '访客',
}
