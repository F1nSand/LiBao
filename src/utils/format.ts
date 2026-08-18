/** 格式化工具（docs/02 §3 utils/） */
import type { TokenUsage } from '@/types'

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

/** token 用量摘要（气泡 usage footer / 轨迹台账）：total_tokens 优先，否则 prompt/completion */
export function formatTokens(u: TokenUsage | undefined | null): string {
  if (!u) return ''
  if (u.total_tokens != null) return `${u.total_tokens} tok`
  const p = u.prompt_tokens ?? 0
  const c = u.completion_tokens ?? 0
  return `${p}/${c} tok`
}

/** 成本（¥）：≥0.01 两位小数，更小保留四位（避免 ¥0.00 丢失信息）；与 SystemView/CostChart 币种一致 */
export function formatCost(c: number | undefined | null): string {
  if (c == null) return ''
  const s = c >= 0.01 ? c.toFixed(2) : c.toFixed(4)
  return `¥${s}`
}

function safeJson(v: unknown): string {
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

/** 工具调用摘要（工具轮无文本时的消息占位）：`调用 [名称]：入参摘要`。
 * input 为 string 直接用；对象取各字段值 join（`{expression: "(3+4)*2-1"}` → `(3+4)*2-1`）；其他 JSON。 */
export function toolCallSummary(name: string, input: unknown): string {
  let summary = ''
  if (typeof input === 'string') summary = input
  else if (input && typeof input === 'object' && !Array.isArray(input)) {
    const vals = Object.values(input as Record<string, unknown>).filter((v) => v != null && v !== '')
    summary = vals.map((v) => (typeof v === 'string' ? v : safeJson(v))).join(', ')
  } else if (input != null) {
    summary = safeJson(input)
  }
  return `调用 ${name}${summary ? `：${truncate(summary, 40)}` : ''}`
}
