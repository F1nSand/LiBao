import { ref } from 'vue'

/**
 * 后端接口可用性注册表（接真实后端用）。
 *
 * 背景：mock 对全部接口实现；真实后端尚未实现的端点（trajectory/notifications/users/system 部分）
 * 未注册路由 → FastAPI 默认 HTTP 404（非信封）。业务 404xx 走 AppError handler → HTTP 200 + 信封，
 * 两者在线上不重叠，故「HTTP 404」是「端点未实现」的可靠判别。
 *
 * 降级状态只存内存（Vue ref，http 层/SSE 不依赖 pinia 即可访问）；刷新即清空 →
 * 后端补齐某接口后一次刷新重新探测即恢复，无需手动清理。
 */
export const FEATURE = {
  trajectory: 'trajectory',
  notifications: 'notifications',
  notificationsStream: 'notifications.stream',
  systemLogs: 'system.logs',
  systemTrace: 'system.trace',
  hooks: 'hooks',
  providers: 'settings.providers',
  skills: 'skills',
  workspaces: 'workspaces',
  workspaceReveal: 'workspaces.reveal',
  workspacesFiles: 'workspaces.files',
} as const
export type Feature = (typeof FEATURE)[keyof typeof FEATURE]

// 路由前缀 → feature。只列已知缺失组，避免未知 404 被误标成某个功能降级。
// 注意顺序：更具体的子路由在前（notifications/stream 在 notifications 前，system/logs/trace 在 system/logs 前），
// 使 SSE 流 / trace 详情单独成 feature，不因单点 404 折叠整个功能组。
const FEATURE_ROUTES: Array<[RegExp, Feature]> = [
  [/^\/conversations\/[^/]+\/trajectory/, FEATURE.trajectory],
  [/^\/notifications\/stream/, FEATURE.notificationsStream],
  [/^\/notifications/, FEATURE.notifications],
  [/^\/system\/logs\/trace/, FEATURE.systemTrace],
  [/^\/system\/logs/, FEATURE.systemLogs],
  [/^\/hooks/, FEATURE.hooks],
  [/^\/settings\/providers/, FEATURE.providers],
  [/^\/skills/, FEATURE.skills],
  [/^\/workspaces\/[^/]+\/files\/rename/, FEATURE.workspacesFiles],
  [/^\/workspaces\/[^/]+\/files/, FEATURE.workspacesFiles], // 覆盖 list/content/rename/mkdir/dir-delete；子操作 404 不折叠整页
  [/^\/workspaces\/[^/]+\/reveal/, FEATURE.workspaceReveal],
  [/^\/workspaces/, FEATURE.workspaces],
]

const unavailable = ref<Record<string, boolean>>({})

function normalizeUrl(url: string): string {
  return url.replace(/^\/api\/v1/, '')
}

/** 从请求路径解析 feature；未知路径返回 null（不误标） */
export function featureForUrl(url: string): Feature | null {
  const path = normalizeUrl(url)
  for (const [re, f] of FEATURE_ROUTES) {
    if (re.test(path)) return f
  }
  return null
}

/** 标记某功能后端未实现（一次标记，本会话生效） */
export function markUnavailable(feature: Feature): void {
  unavailable.value[feature] = true
}

/** 查询某功能是否已标记为未实现（reactive，可在组件 computed 中跟踪） */
export function isUnavailable(feature: Feature): boolean {
  return !!unavailable.value[feature]
}

/** 按 URL 查询：该 URL 所属功能是否已标记未实现 */
export function isUrlUnavailable(url: string): boolean {
  const f = featureForUrl(url)
  return !!f && isUnavailable(f)
}

/** 按 URL 打标：将该 URL 所属功能标记为未实现（未知路径静默） */
export function markUnavailableForUrl(url: string): void {
  const f = featureForUrl(url)
  if (f) markUnavailable(f)
}

/** 测试用：清空所有标记 */
export function resetUnavailable(): void {
  unavailable.value = {}
}
