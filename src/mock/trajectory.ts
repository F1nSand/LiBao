import type { Message, TrajectoryNode } from '@/types'

/** c_long 长会话（演示「加载更早历史」分页）：程序化生成 55 轮 user/assistant */
export function buildLongConversationNodes(): TrajectoryNode[] {
  const nodes: TrajectoryNode[] = []
  const base = Date.now() - 120 * 60_000
  for (let i = 1; i <= 55; i++) {
    nodes.push({ seq: 0, kind: 'user', time: base + i * 120_000, content: `长会话问题 ${i}` })
    nodes.push({
      seq: 0,
      kind: 'assistant',
      time: base + i * 120_000 + 3000,
      content: `长会话回答 ${i}：这是一段示例回复内容，用于演示轨迹分页加载。`,
      token_usage: { prompt_tokens: 40 + i, completion_tokens: 20 + i, total_tokens: 60 + i * 2 },
      tool_calls:
        i % 3 === 0
          ? [
              {
                tool_call_id: `tc_long_${i}`,
                tool_name: 'web_search',
                input: { query: `q${i}` },
                output: { hits: 3 },
                ok: true,
                duration_ms: 300,
                position: 0,
              },
            ]
          : [],
    })
  }
  return nodes.map((n, i) => ({ ...n, seq: i + 1 }))
}

/**
 * 由会话消息派生轨迹节点（kind 映射 + tool_calls 展开）。
 * c_001 额外注入 context(diff)/thinking/compaction 以演示新 kind。
 */
export function buildTrajectoryNodes(conversationId: string, list: Message[]): TrajectoryNode[] {
  const nodes: TrajectoryNode[] = []
  for (const m of list) {
    if (m.role === 'system') {
      const diff = (m as Message & { diff?: { before: string; after: string } }).diff
      nodes.push({ seq: 0, kind: 'context', time: Date.parse(m.created_at), content: m.content, diff })
    } else if (m.role === 'user') {
      nodes.push({ seq: 0, kind: 'user', time: Date.parse(m.created_at), content: m.content })
    } else if (m.role === 'assistant') {
      nodes.push({
        seq: 0,
        kind: 'assistant',
        time: Date.parse(m.created_at),
        content: m.content || undefined,
        token_usage: m.token_usage,
        trace_id: m.trace_id,
        tool_calls: (m.tool_calls ?? []).map((t) => ({
          tool_call_id: t.tool_call_id,
          tool_name: t.tool_name,
          input: t.input,
          output: t.output,
          ok: !['failed', 'error', 'timeout', 'cancelled'].includes(t.status ?? ''),
          duration_ms: t.duration_ms,
          position: t.position,
        })),
      })
    }
  }

  if (conversationId === 'c_001') {
    const first = nodes[0]
    nodes.unshift({
      seq: 0,
      kind: 'context',
      time: (first?.time ?? Date.now()) - 30_000,
      content: 'system prompt：你是 Agent 平台的助手，可使用工具回答用户问题。',
      diff: {
        before: 'system prompt：你是平台的助手。',
        after: 'system prompt：你是 Agent 平台的助手，可使用工具回答用户问题。',
      },
    })
    const asst = nodes.find((n) => n.kind === 'assistant')
    if (asst) asst.thinking = '先解析表达式 6*7，判断需要计算 → 调用 calculator 工具，随后汇总结果。'
    nodes.push({
      seq: 0,
      kind: 'compaction',
      time: (nodes[nodes.length - 1]?.time ?? Date.now()) + 30_000,
      content: '上下文已压缩：保留本次计算结论与后续对话要点。',
    })
  }

  return nodes.map((n, i) => ({ ...n, seq: i + 1 }))
}

/** 分页：默认取最后 limit 条；before_seq 取更早一页 */
export function paginateTrajectory(
  nodes: TrajectoryNode[],
  beforeSeq?: number,
  limit = 50,
): { nodes: TrajectoryNode[]; hasMore: boolean } {
  const arr = beforeSeq != null ? nodes.filter((n) => n.seq < beforeSeq) : nodes
  return { nodes: arr.slice(Math.max(0, arr.length - limit)), hasMore: arr.length > limit }
}
