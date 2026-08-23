import { describe, expect, it } from 'vitest'
import type { TrajectoryNode } from '@/types'
import { cellMatches, flatCells, foldTrajectory, kindColor, kindLane } from './trajectory'

function user(seq: number, content: string, time = seq * 1000): TrajectoryNode {
  return { seq, kind: 'user', time, content }
}
function assistant(seq: number, content: string, toolCalls: TrajectoryNode['tool_calls'] = [], time = seq * 1000): TrajectoryNode {
  return { seq, kind: 'assistant', time, content, tool_calls: toolCalls }
}

describe('foldTrajectory（对话轨迹折叠）', () => {
  it('user→assistant 一轮 = 一个 Turn（userCell + Message 组），全局 index 递增', () => {
    const turns = foldTrajectory([user(1, '你好'), assistant(2, '你好！')])
    expect(turns).toHaveLength(1)
    expect(turns[0].index).toBe(1)
    expect(turns[0].userCell?.kind).toBe('user')
    expect(turns[0].userCell?.index).toBe(1)
    expect(turns[0].groups).toHaveLength(1)
    expect(turns[0].groups[0].title).toBe('Message')
    expect(turns[0].groups[0].cells.map((c) => c.kind)).toEqual(['message'])
    expect(turns[0].groups[0].cells[0].index).toBe(2)
  })

  it('工具调用展开为 tool cell（按 position 排序，全局 index 续增）', () => {
    const turns = foldTrajectory([
      user(1, '算一下'),
      assistant(2, '结果：42', [
        { tool_call_id: 't2', tool_name: 'calc', input: {}, output: { result: 42 }, ok: true, duration_ms: 200, position: 1 },
        { tool_call_id: 't1', tool_name: 'calc', input: { expression: '6*7' }, output: {}, ok: true, duration_ms: 100, position: 0 },
      ]),
    ])
    const g = turns[0].groups[0]
    expect(g.cells.map((c) => c.kind)).toEqual(['message', 'tool', 'tool'])
    expect(g.cells[1].toolCallId).toBe('t1') // position 0 优先
    expect(g.cells[1].index).toBe(3)
    expect(g.cells[2].toolCallId).toBe('t2')
    expect(g.cells[2].index).toBe(4)
    expect(g.cells[2].durationMs).toBe(200)
    expect(g.cells[2].isError).toBe(false)
  })

  it('content 为空的工具轮 → message cell 占位「调用 [工具]」+ tool cell', () => {
    const turns = foldTrajectory([
      user(1, '查'),
      assistant(2, '', [
        { tool_call_id: 't', tool_name: 'search', input: { query: 'sse' }, output: {}, ok: true, duration_ms: 10, position: 0 },
      ]),
    ])
    expect(turns[0].groups[0].cells.map((c) => c.kind)).toEqual(['message', 'tool'])
    expect(turns[0].groups[0].cells[0].content).toContain('调用 search')
  })

  it('assistant 开头（无前置 user）→ userCell 为 null', () => {
    const turns = foldTrajectory([assistant(1, '开场')])
    expect(turns[0].userCell).toBeNull()
    expect(turns[0].groups[0].title).toBe('Message')
  })

  it('同一 Turn 多个 assistant 节点（逐轮消息）→ Message（含工具）+ Step 1', () => {
    const turns = foldTrajectory([
      user(1, 'q'),
      assistant(2, '检索中', [{ tool_call_id: 't1', tool_name: 'web_search', input: {}, output: {}, ok: true, position: 0 }]),
      assistant(3, '最终答案'),
    ])
    expect(turns).toHaveLength(1)
    expect(turns[0].groups.map((g) => g.title)).toEqual(['Message', 'Step 1'])
    expect(turns[0].groups[0].cells.map((c) => c.kind)).toEqual(['message', 'tool'])
    expect(turns[0].groups[1].cells.map((c) => c.kind)).toEqual(['message'])
  })

  it('连续 user → 开两个 Turn，index 全局递增', () => {
    const turns = foldTrajectory([user(1, 'u1'), user(2, 'u2')])
    expect(turns.map((t) => t.index)).toEqual([1, 2])
    expect(turns[0].userCell?.index).toBe(1)
    expect(turns[1].userCell?.index).toBe(2)
  })

  it('summary 文案：Turn 与 Group', () => {
    const turns = foldTrajectory([
      user(1, 'q'),
      assistant(2, 'a', [{ tool_call_id: 't', tool_name: 'calc', input: {}, output: {}, ok: true, duration_ms: 320, position: 0 }]),
    ])
    expect(turns[0].summary).toBe('1 步 · 1 工具')
    expect(turns[0].groups[0].summary).toBe('320ms · 1 工具')
  })

  it('flatCells 摊平 user + 组内全部 cell', () => {
    const turns = foldTrajectory([
      user(1, 'q'),
      assistant(2, 'a', [{ tool_call_id: 't', tool_name: 'x', input: {}, output: {}, ok: true, position: 0 }]),
    ])
    expect(flatCells(turns).map((c) => c.index)).toEqual([1, 2, 3])
  })

  it('cellMatches 命中摘要 / 工具名', () => {
    const turns = foldTrajectory([
      user(1, '什么是 SSE'),
      assistant(2, 'a', [{ tool_call_id: 't', tool_name: 'web_search', input: {}, output: {}, ok: true, position: 0 }]),
    ])
    const cells = flatCells(turns)
    expect(cellMatches(cells[0], 'sse')).toBe(true)
    expect(cellMatches(cells[2], 'web_search')).toBe(true)
    expect(cellMatches(cells[0], 'web')).toBe(false)
  })

  it('kindColor：错误工具红色，其余按类返回主题 var（USER/CONTEXT/ASSISTANT/TOOL）', () => {
    expect(kindColor('tool', true)).toBe('#ef4444')
    expect(kindColor('user')).toBe('var(--tj-user)')
    expect(kindColor('context')).toBe('var(--tj-context)')
    expect(kindColor('message')).toBe('var(--tj-assistant)')
    expect(kindColor('tool')).toBe('var(--tj-tool)')
    expect(kindColor('compacted')).toBe('var(--tj-muted)')
  })

  it('context 节点进当前 Turn 的 contextCells（含 diff）', () => {
    const turns = foldTrajectory([
      user(1, 'q'),
      { seq: 2, kind: 'context', time: 2000, content: 'system prompt', diff: { before: 'a', after: 'b' } },
      assistant(3, 'a1'),
    ])
    expect(turns).toHaveLength(1)
    expect(turns[0].contextCells.map((c) => c.kind)).toEqual(['context'])
    expect(turns[0].contextCells[0].diff).toEqual({ before: 'a', after: 'b' })
    expect(flatCells(turns).map((c) => c.kind)).toEqual(['user', 'context', 'message'])
  })

  it('steering 节点开新 Turn（userCell kind=steering）', () => {
    const turns = foldTrajectory([{ seq: 1, kind: 'steering', time: 1000, content: '引导' }])
    expect(turns).toHaveLength(1)
    expect(turns[0].userCell?.kind).toBe('steering')
  })

  it('compaction 节点建 Compaction 组（单个 compacted cell）', () => {
    const turns = foldTrajectory([user(1, 'q'), { seq: 2, kind: 'compaction', time: 2000, content: '压缩摘要' }])
    expect(turns[0].groups).toHaveLength(1)
    expect(turns[0].groups[0].title).toBe('Compaction 2')
    expect(turns[0].groups[0].cells.map((c) => c.kind)).toEqual(['compacted'])
  })

  it('assistant 带 thinking → message cell 携带 thinking', () => {
    const turns = foldTrajectory([{ seq: 1, kind: 'assistant', time: 1000, content: 'a', thinking: '推理…' }])
    expect(turns[0].groups[0].cells[0].thinking).toBe('推理…')
  })

  it('kindLane：tool=2 / message·compacted=1 / 其余=0', () => {
    expect(kindLane('tool')).toBe(2)
    expect(kindLane('message')).toBe(1)
    expect(kindLane('compacted')).toBe(1)
    expect(kindLane('user')).toBe(0)
    expect(kindLane('context')).toBe(0)
    expect(kindLane('steering')).toBe(0)
  })
})
