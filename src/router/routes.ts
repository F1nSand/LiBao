import type { RouteRecordRaw } from 'vue-router'

export interface AppRouteMeta {
  title: string
  icon?: string
}

export interface MenuItem {
  path: string
  title: string
  icon: string
  children?: MenuItem[]
}

/** 菜单项配置（《02》前端设计 §4）：侧栏菜单；设置项带 children（工具/记忆/系统/设置 子栏） */
export const menuItems: MenuItem[] = [
  // 工作区（M7-B，《02》前端设计 §4）：入口在对话上方；内部 = 文件资源管理器 + 工作区对话
  { path: '/workspace', title: '工作区', icon: 'Grid' },
  { path: '/chat', title: '对话', icon: 'ChatDotRound' },
  { path: '/kb', title: '知识库', icon: 'FolderOpened' },
  {
    path: '/settings',
    title: '设置',
    icon: 'Setting',
    children: [
      { path: '/settings', title: '设置', icon: 'Setting' },
      { path: '/tools', title: '工具', icon: 'Tools' },
      { path: '/skills', title: '技能', icon: 'Collection' },
      { path: '/memory', title: '记忆', icon: 'Tickets' },
      { path: '/system', title: '系统', icon: 'Odometer' },
    ],
  },
]

/** 属于「设置」组的路由（子栏在这些页面显示） */
export const SETTINGS_ROUTES = ['/tools', '/skills', '/memory', '/system', '/settings']
export const isSettingsRoute = (path: string): boolean => SETTINGS_ROUTES.includes(path)

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/chat',
  },
  {
    path: '/workspace',
    name: 'workspace',
    component: () => import('@/views/WorkspaceView.vue'),
    meta: { title: '工作区', icon: 'Grid' } satisfies AppRouteMeta,
  },
  {
    path: '/workspace/:id',
    name: 'workspace-detail',
    component: () => import('@/views/WorkspaceDetailView.vue'),
    meta: { title: '工作区' } satisfies AppRouteMeta,
  },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { title: '对话', icon: 'ChatDotRound' } satisfies AppRouteMeta,
  },
  {
    // 对话轨迹（《02》前端设计 §6.3）：按会话隔离的只读查看页，不进侧栏菜单
    path: '/trajectory/:conversationId',
    name: 'trajectory',
    component: () => import('@/views/TrajectoryView.vue'),
    meta: { title: '对话轨迹' } satisfies AppRouteMeta,
  },
  {
    path: '/tools',
    name: 'tools',
    component: () => import('@/views/ToolsView.vue'),
    meta: { title: '工具', icon: 'Tools' } satisfies AppRouteMeta,
  },
  {
    path: '/skills',
    name: 'skills',
    component: () => import('@/views/SkillsView.vue'),
    meta: { title: '技能', icon: 'Collection' } satisfies AppRouteMeta,
  },
  {
    path: '/kb',
    name: 'kb',
    component: () => import('@/views/KbView.vue'),
    meta: { title: '知识库', icon: 'FolderOpened' } satisfies AppRouteMeta,
  },
  {
    path: '/memory',
    name: 'memory',
    component: () => import('@/views/MemoryView.vue'),
    meta: { title: '记忆', icon: 'Tickets' } satisfies AppRouteMeta,
  },
  {
    path: '/system',
    name: 'system',
    component: () => import('@/views/SystemView.vue'),
    meta: { title: '系统', icon: 'Odometer' } satisfies AppRouteMeta,
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { title: '设置', icon: 'Setting' } satisfies AppRouteMeta,
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/chat',
  },
]
