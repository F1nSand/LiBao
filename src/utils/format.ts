/** 格式化工具（docs/02 §3 utils/） */

export function formatBytes(bytes: number | undefined | null): string {
  if (bytes == null) return '-'
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

export function formatDate(iso: string | undefined | null): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { hour12: false })
}

export function formatDuration(ms: number | undefined | null): string {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

/** epoch ms → HH:mm:ss（轨迹时间轴 / 详情） */
export function formatTime(ms: number | undefined | null): string {
  if (ms == null || Number.isNaN(ms)) return '-'
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function truncate(s: string | undefined | null, max = 40): string {
  if (!s) return ''
  return s.length > max ? `${s.slice(0, max)}…` : s
}
