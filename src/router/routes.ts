import type { RouteRecordRaw } from 'vue-router'
import type { Role } from '@/types'

export interface AppRouteMeta {
  title: string
  icon?: string
  requiresAuth?: boolean
  roles?: Role[]
}

export interface MenuItem {
  path: string
  title: string
  icon: string
  roles?: Role[]
  children?: MenuItem[]
}

/** 菜单项配置（docs/02 §4）：侧栏菜单；设置项带 children（工具/记忆/系统/设置 子栏） */
export const menuItems: MenuItem[] = [
  // 工作区（单通用 Agent 后置项目，docs/07）：入口在对话上方，内部设计待定
  { path: '/workspace', title: '工作区', icon: 'Grid' },
  { path: '/chat', title: '对话', icon: 'ChatDotRound' },
  { path: '/kb', title: '知识库', icon: 'FolderOpened', roles: ['admin', 'developer'] },
  {
    path: '/settings',
    title: '设置',
    icon: 'Setting',
    roles: ['admin'],
    children: [
      { path: '/settings', title: '设置', icon: 'Setting', roles: ['admin'] },
      { path: '/tools', title: '工具', icon: 'Tools', roles: ['admin', 'developer'] },
      { path: '/skills', title: '技能', icon: 'Collection', roles: ['admin', 'developer'] },
      { path: '/memory', title: '记忆', icon: 'Tickets' },
      { path: '/system', title: '系统', icon: 'Odometer', roles: ['admin'] },
    ],
  },
]

/** 属于「设置」组的路由（子栏在这些页面显示） */
export const SETTINGS_ROUTES = ['/tools', '/skills', '/memory', '/system', '/settings']
export const isSettingsRoute = (path: string): boolean => SETTINGS_ROUTES.includes(path)

export const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', requiresAuth: false } satisfies AppRouteMeta,
  },
  {
    path: '/',
    redirect: '/chat',
  },
  {
    path: '/workspace',
    name: 'workspace',
    component: () => import('@/views/WorkspaceView.vue'),
    meta: { title: '工作区', icon: 'Grid', requiresAuth: true } satisfies AppRouteMeta,
  },
  {
    path: '/workspace/:id',
    name: 'workspace-detail',
    component: () => import('@/views/WorkspaceDetailView.vue'),
    meta: { title: '工作区', requiresAuth: true } satisfies AppRouteMeta,
  },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { title: '对话', icon: 'ChatDotRound', requiresAuth: true } satisfies AppRouteMeta,
  },
  {
    // 对话轨迹（docs/02 §6.3）：按会话隔离的只读查看页，不进侧栏菜单
    path: '/trajectory/:conversationId',
    name: 'trajectory',
    component: () => import('@/views/TrajectoryView.vue'),
    meta: { title: '对话轨迹', requiresAuth: true } satisfies AppRouteMeta,
  },
  {
    path: '/tools',
    name: 'tools',
    component: () => import('@/views/ToolsView.vue'),
    meta: { title: '工具', icon: 'Tools', requiresAuth: true, roles: ['admin', 'developer'] } satisfies AppRouteMeta,
  },
  {
    path: '/skills',
    name: 'skills',
    component: () => import('@/views/SkillsView.vue'),
    meta: { title: '技能', icon: 'Collection', requiresAuth: true, roles: ['admin', 'developer'] } satisfies AppRouteMeta,
  },
  {
    path: '/kb',
    name: 'kb',
    component: () => import('@/views/KbView.vue'),
    meta: { title: '知识库', icon: 'FolderOpened', requiresAuth: true, roles: ['admin', 'developer'] } satisfies AppRouteMeta,
  },
  {
    path: '/memory',
    name: 'memory',
    component: () => import('@/views/MemoryView.vue'),
    meta: { title: '记忆', icon: 'Tickets', requiresAuth: true } satisfies AppRouteMeta,
  },
  {
    path: '/system',
    name: 'system',
    component: () => import('@/views/SystemView.vue'),
    meta: { title: '系统', icon: 'Odometer', requiresAuth: true, roles: ['admin'] } satisfies AppRouteMeta,
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { title: '设置', icon: 'Setting', requiresAuth: true, roles: ['admin'] } satisfies AppRouteMeta,
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/chat',
  },
]
