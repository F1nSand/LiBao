/**
 * 主题系统（docs/02 §7）：CSS 变量覆盖，全局生效（主色 + 侧边栏 + Element 主色），内容区保持浅色。
 * 9 套：6 纯色（一深一浅）+ 3 撞色；localStorage 持久化（key: agent.theme）。
 */
export interface ThemeDef {
  id: string
  name: string
  type: 'solid' | 'contrast'
  /** 主题面板预览色 */
  preview: { primary: string; sidebar: string }
  vars: Record<string, string>
}

export const DEFAULT_THEME = 'indigo'
const THEME_KEY = 'agent.theme'

/* ---------- 颜色工具 ---------- */
function hexMix(a: string, b: string, ratio: number): string {
  const pa = parseInt(a.slice(1), 16)
  const pb = parseInt(b.slice(1), 16)
  const ra = (pa >> 16) & 255
  const ga = (pa >> 8) & 255
  const ba = pa & 255
  const rb = (pb >> 16) & 255
  const gb = (pb >> 8) & 255
  const bb = pb & 255
  const r = Math.round(ra + (rb - ra) * ratio)
  const g = Math.round(ga + (gb - ga) * ratio)
  const bl = Math.round(ba + (bb - ba) * ratio)
  return `#${((1 << 24) | (r << 16) | (g << 8) | bl).toString(16).slice(1)}`
}
const lighten = (hex: string, r: number) => hexMix(hex, '#ffffff', r)
const darken = (hex: string, r: number) => hexMix(hex, '#000000', r)

/** 纯色主题：深侧边栏 + 同色系亮主色；会话列表浅色框 = 侧边栏提亮 6% */
function solidTheme(id: string, name: string, primary: string, sidebar: string): ThemeDef {
  return {
    id,
    name,
    type: 'solid',
    preview: { primary, sidebar },
    vars: {
      '--app-primary': primary,
      '--app-primary-dark': darken(primary, 0.12),
      '--el-color-primary': primary,
      '--el-color-primary-light-3': lighten(primary, 0.3),
      '--el-color-primary-light-5': lighten(primary, 0.5),
      '--el-color-primary-light-7': lighten(primary, 0.7),
      '--el-color-primary-light-8': lighten(primary, 0.8),
      '--el-color-primary-light-9': lighten(primary, 0.9),
      '--el-color-primary-dark-2': darken(primary, 0.15),
      '--app-sidebar-bg': sidebar,
      '--app-sidebar-border': lighten(sidebar, 0.08),
      '--app-sidebar-logo-bg': darken(sidebar, 0.08),
      '--app-sidebar-conv-bg': lighten(sidebar, 0.06),
      '--app-sidebar-text': '#a3a3c2',
      '--app-sidebar-text-active': '#ffffff',
      '--app-sidebar-item-hover': 'rgba(255,255,255,0.06)',
      '--app-sidebar-item-active-bg': 'rgba(255,255,255,0.16)',
    },
  }
}

const solidThemes: ThemeDef[] = [
  solidTheme('indigo', '靛蓝', '#6366f1', '#1e1e2f'),
  solidTheme('navy', '墨蓝', '#3b82f6', '#16223a'),
  solidTheme('green', '翠绿', '#22c55e', '#123c2e'),
  solidTheme('violet', '紫罗兰', '#a855f7', '#241a3c'),
  solidTheme('amber', '赭橙', '#f59e0b', '#3a2a14'),
  solidTheme('crimson', '绯红', '#ef4444', '#3a1620'),
]

const contrastThemes: ThemeDef[] = [
  {
    id: 'mono',
    name: '黑白',
    type: 'contrast',
    preview: { primary: '#000000', sidebar: '#0d0d0d' },
    vars: {
      '--app-primary': '#000000',
      '--app-primary-dark': '#333333',
      '--el-color-primary': '#000000',
      '--el-color-primary-light-3': '#4d4d4d',
      '--el-color-primary-light-5': '#808080',
      '--el-color-primary-light-7': '#b3b3b3',
      '--el-color-primary-light-8': '#cccccc',
      '--el-color-primary-light-9': '#e6e6e6',
      '--el-color-primary-dark-2': '#000000',
      '--app-sidebar-bg': '#0d0d0d',
      '--app-sidebar-border': '#2a2a2a',
      '--app-sidebar-logo-bg': '#050505',
      '--app-sidebar-conv-bg': '#1f1f1f',
      '--app-sidebar-text': '#c9c9c9',
      '--app-sidebar-text-active': '#ffffff',
      '--app-sidebar-item-hover': 'rgba(255,255,255,0.08)',
      '--app-sidebar-item-active-bg': 'rgba(255,255,255,0.16)',
    },
  },
  {
    id: 'redblue',
    name: '浅红×浅蓝',
    type: 'contrast',
    preview: { primary: '#3b82f6', sidebar: '#fca5a5' },
    vars: {
      '--app-primary': '#3b82f6',
      '--app-primary-dark': '#2563eb',
      '--el-color-primary': '#3b82f6',
      '--el-color-primary-light-3': '#93c5fd',
      '--el-color-primary-light-5': '#bfdbfe',
      '--el-color-primary-light-7': '#dbeafe',
      '--el-color-primary-light-8': '#eff6ff',
      '--el-color-primary-light-9': '#f5f9ff',
      '--el-color-primary-dark-2': '#2563eb',
      '--app-sidebar-bg': '#fca5a5',
      '--app-sidebar-border': '#fca5a5',
      '--app-sidebar-logo-bg': '#f48f8f',
      '--app-sidebar-conv-bg': '#ffffff',
      '--app-sidebar-text': '#7f1d1d',
      '--app-sidebar-text-active': '#ffffff',
      '--app-sidebar-item-hover': 'rgba(0,0,0,0.06)',
      '--app-sidebar-item-active-bg': 'rgba(127,29,29,0.12)',
    },
  },
  {
    id: 'redyellow',
    name: '红黄',
    type: 'contrast',
    preview: { primary: '#d97706', sidebar: '#dc2626' },
    vars: {
      '--app-primary': '#d97706',
      '--app-primary-dark': '#b45309',
      '--el-color-primary': '#d97706',
      '--el-color-primary-light-3': '#f59e0b',
      '--el-color-primary-light-5': '#fbbf24',
      '--el-color-primary-light-7': '#fde68a',
      '--el-color-primary-light-8': '#fef3c7',
      '--el-color-primary-light-9': '#fffbeb',
      '--el-color-primary-dark-2': '#b45309',
      '--app-sidebar-bg': '#dc2626',
      '--app-sidebar-border': '#ef4444',
      '--app-sidebar-logo-bg': '#b91c1c',
      '--app-sidebar-conv-bg': '#ef4444',
      '--app-sidebar-text': '#ffe4e6',
      '--app-sidebar-text-active': '#ffffff',
      '--app-sidebar-item-hover': 'rgba(255,255,255,0.12)',
      '--app-sidebar-item-active-bg': 'rgba(255,255,255,0.2)',
    },
  },
]

export const THEMES: ThemeDef[] = [...solidThemes, ...contrastThemes]

export function getTheme(id: string | null | undefined): ThemeDef {
  return THEMES.find((t) => t.id === id) ?? THEMES[0]
}

/** 将主题 CSS 变量写到 :root */
export function applyTheme(id: string): void {
  const theme = getTheme(id)
  if (typeof document === 'undefined') return
  const root = document.documentElement
  for (const [k, v] of Object.entries(theme.vars)) root.style.setProperty(k, v)
}

export function setStoredTheme(id: string): void {
  try {
    localStorage.setItem(THEME_KEY, id)
  } catch {
    /* ignore */
  }
}

export function getStoredTheme(): string {
  try {
    return localStorage.getItem(THEME_KEY) ?? DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}
