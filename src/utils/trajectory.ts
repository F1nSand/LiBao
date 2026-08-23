import type { TokenUsage, TrajectoryNode, TrajectoryToolCall } from '@/types'
import { formatDuration, toolCallSummary, truncate } from './format'

/**
 * 对话轨迹折叠（docs/02 §6.3）：`TrajectoryNode[]` → Turn → Group → Cell。
 * 纯函数，便于单测；组件只消费折叠后的视图模型。
 * 规则：user/steering 节点开新 Turn（userCell）；context 节点进当前 Turn 的 contextCells；
 * compaction 节点建 `Compaction <seq>` 组（单个 compacted cell）；assistant 节点建组
 * （首个 `Message`，后续 `Step N`），组内 = message cell（content 空则省略，附 thinking）+ 按 position 排序的 tool cell。
 */
export type TrajectoryCellKind = 'user' | 'steering' | 'context' | 'message' | 'tool' | 'compacted'

export interface TrajectoryCell {
  /** 全局唯一序号（#N，跨 Turn/组递增） */
  index: number
  kind: TrajectoryCellKind
  /** 单行摘要 */
  text: string
  /** markdown 预览 */
  previewMarkdown: string
  content?: string
  input?: unknown
  output?: unknown
  /** assistant 推理（可空，默认折叠展示） */
  thinking?: string
  /** context/system 更新的前后差异 */
  diff?: { before: string; after: string }
  isError?: boolean
  /** epoch ms */
  startedAt: number
  /** 自身耗时 ms（tool 有值，其余无） */
  durationMs?: number
  tokenUsage?: TokenUsage
  toolCallId?: string
  toolName?: string
}

export interface TrajectoryGroup {
  title: string // 'Message' | `Step N` | `Compaction <seq>`
  step: number
  cells: TrajectoryCell[]
  /** 组耗时 · N 工具 */
  summary: string
  startedAt: number
}

export interface TrajectoryTurn {
  index: number // Turn N
  userCell: TrajectoryCell | null
  contextCells: TrajectoryCell[]
  groups: TrajectoryGroup[]
  /** N 步 · M 工具 */
  summary: string
  startedAt: number
}

function safeStringify(v: unknown): string {
  if (v === undefined) return ''
  try {
    return typeof v === 'string' ? v : JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function makeUserCell(n: TrajectoryNode, index: number, kind: 'user' | 'steering'): TrajectoryCell {
  return {
    index,
    kind,
    text: truncate((n.content ?? '').replace(/\n/g, ' ') || (kind === 'steering' ? '（引导）' : '（空）'), 60),
    previewMarkdown: n.content ?? '',
    content: n.content,
    startedAt: n.time,
  }
}

function makeContextCell(n: TrajectoryNode, index: number): TrajectoryCell {
  return {
    index,
    kind: 'context',
    text: truncate((n.content ?? '').replace(/\n/g, ' ') || '（上下文）', 60),
    previewMarkdown: n.content ?? '',
    content: n.content,
    diff: n.diff,
    startedAt: n.time,
  }
}

function makeCompactedCell(n: TrajectoryNode, index: number): TrajectoryCell {
  return {
    index,
    kind: 'compacted',
    text: truncate(n.content ?? '上下文压缩', 60),
    previewMarkdown: n.content ?? '',
    content: n.content,
    startedAt: n.time,
  }
}

function makeMessageCell(n: TrajectoryNode, index: number): TrajectoryCell {
  return {
    index,
    kind: 'message',
    text: truncate((n.content ?? '').replace(/\n/g, ' '), 60),
    previewMarkdown: n.content ?? '',
    content: n.content,
    thinking: n.thinking,
    startedAt: n.time,
    tokenUsage: n.token_usage,
  }
}

function makeToolCell(n: TrajectoryNode, tc: TrajectoryToolCall, index: number): TrajectoryCell {
  const argsRaw = safeStringify(tc.input)
  // subagent 派发（agent 控制）标记：⇄ 派发 subagent，弱化显示（docs/02 §6.3）
  const isDispatch = tc.tool_name === 'dispatch_subagent'
  return {
    index,
    kind: 'tool',
    text: isDispatch ? `⇄ 派发 subagent ${truncate(argsRaw, 40)}`.trim() : `${tc.tool_name} ${truncate(argsRaw, 40)}`.trim(),
    previewMarkdown: tc.output !== undefined ? safeStringify(tc.output) : argsRaw,
    input: tc.input,
    output: tc.output,
    isError: tc.ok === false,
    startedAt: n.time,
    durationMs: tc.duration_ms,
    toolCallId: tc.tool_call_id,
    toolName: tc.tool_name,
  }
}

export function foldTrajectory(nodes: TrajectoryNode[]): TrajectoryTurn[] {
  const turns: TrajectoryTurn[] = []
  let current: TrajectoryTurn | null = null
  let idx = 0

  const newTurn = (startedAt: number): TrajectoryTurn => {
    const t: TrajectoryTurn = {
      index: turns.length + 1,
      userCell: null,
      contextCells: [],
      groups: [],
      summary: '',
      startedAt,
    }
    turns.push(t)
    return t
  }

  for (const n of nodes) {
    switch (n.kind) {
      case 'user':
      case 'steering': {
        current = newTurn(n.time)
        current.userCell = makeUserCell(n, ++idx, n.kind)
        break
      }
      case 'context': {
        if (!current) current = newTurn(n.time)
        current.contextCells.push(makeContextCell(n, ++idx))
        break
      }
      case 'compaction': {
        if (!current) current = newTurn(n.time)
        current.groups.push({
          title: `Compaction ${n.seq}`,
          step: current.groups.length,
          cells: [makeCompactedCell(n, ++idx)],
          summary: '压缩',
          startedAt: n.time,
        })
        break
      }
      case 'assistant': {
        if (!current) current = newTurn(n.time)
        const step = current.groups.length
        const group: TrajectoryGroup = {
          title: step === 0 ? 'Message' : `Step ${step}`,
          step,
          cells: [],
          summary: '',
          startedAt: n.time,
        }
        const tcs = [...(n.tool_calls ?? [])].sort((a, b) => a.position - b.position)
        if (n.content && n.content.trim()) {
          group.cells.push(makeMessageCell(n, ++idx))
        } else if (tcs.length) {
          // 工具轮无文本 → message cell 占位「调用 [工具]：入参」（与聊天气泡一致）
          const first = toolCallSummary(tcs[0].tool_name, tcs[0].input)
          const placeholder = tcs.length > 1 ? `${first} 等 ${tcs.length} 个工具` : first
          group.cells.push(makeMessageCell({ ...n, content: placeholder }, ++idx))
        }
        for (const tc of tcs) group.cells.push(makeToolCell(n, tc, ++idx))
        const durs = tcs.filter((t) => t.duration_ms != null).map((t) => t.duration_ms as number)
        group.summary = `${formatDuration(durs.length ? durs.reduce((a, b) => a + b, 0) : null)} · ${tcs.length} 工具`
        current.groups.push(group)
        break
      }
    }
  }

  for (const t of turns) {
    const toolCount = t.groups.reduce((s, g) => s + g.cells.filter((c) => c.kind === 'tool').length, 0)
    t.summary = `${t.groups.length} 步 · ${toolCount} 工具`
  }
  return turns
}

/** 摊平所有 Cell（含 contextCells；供搜索 / 选中定位） */
export function flatCells(turns: TrajectoryTurn[]): TrajectoryCell[] {
  const cells: TrajectoryCell[] = []
  for (const t of turns) {
    if (t.userCell) cells.push(t.userCell)
    for (const c of t.contextCells) cells.push(c)
    for (const g of t.groups) cells.push(...g.cells)
  }
  return cells
}

/** 单元格是否命中搜索词（摘要 / 全文 / 工具名 / 推理） */
export function cellMatches(c: TrajectoryCell, q: string): boolean {
  if (!q) return true
  const k = q.trim().toLowerCase()
  return [c.text, c.content, c.toolName, c.thinking].some((s) => (s ?? '').toLowerCase().includes(k))
}

export function kindLabel(kind: TrajectoryCellKind): string {
  switch (kind) {
    case 'user':
      return 'USER'
    case 'steering':
      return 'SYSTEM'
    case 'context':
      return 'CONTEXT'
    case 'message':
      return 'ASSISTANT'
    case 'tool':
      return 'TOOL'
    default:
      return 'COMPACTED'
  }
}

/** 标签主色（甘特块 / 标签名），返回主题 var；错误优先红 */
export function kindColor(kind: TrajectoryCellKind, isError?: boolean): string {
  if (isError) return '#ef4444'
  switch (kind) {
    case 'user':
      return 'var(--tj-user)'
    case 'steering':
    case 'context':
      return 'var(--tj-context)'
    case 'message':
      return 'var(--tj-assistant)'
    case 'tool':
      return 'var(--tj-tool)'
    default:
      return 'var(--tj-muted)'
  }
}

/** 标签框浅色背景（圆角矩形），返回主题 var */
export function kindBgColor(kind: TrajectoryCellKind): string {
  switch (kind) {
    case 'user':
      return 'var(--tj-user-bg)'
    case 'steering':
    case 'context':
      return 'var(--tj-context-bg)'
    case 'message':
      return 'var(--tj-assistant-bg)'
    case 'tool':
      return 'var(--tj-tool-bg)'
    default:
      return 'var(--tj-muted-bg)'
  }
}

/** 轮次收起省略摘要：`N steps · M tools`（组数 = steps，组内 tool cell 数 = tools） */
export function turnStepsSummary(turn: TrajectoryTurn): string {
  const steps = turn.groups.length
  const tools = turn.groups.reduce((n, g) => n + g.cells.filter((c) => c.kind === 'tool').length, 0)
  return `${steps} steps · ${tools} tools`
}

/** 时间轴泳道：0=Input(user/steering/context) 1=Model(message/compacted) 2=Tools(tool) */
export function kindLane(kind: TrajectoryCellKind): number {
  if (kind === 'tool') return 2
  if (kind === 'message' || kind === 'compacted') return 1
  return 0
}
