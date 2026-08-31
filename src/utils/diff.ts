/** 行级 LCS 结构化 diff（《02》前端设计 §6.3 Diff 标签）：added / deleted / context 三类段 */
export type DiffSegment = { type: 'add' | 'del' | 'ctx'; lines: string[] }

/**
 * 基于 LCS 的逐行 diff，返回有序段（连续同类行合并）。
 * before/after 为纯文本，按 `\n` 切分。
 */
export function lineDiff(before: string, after: string): DiffSegment[] {
  const a = before === '' ? [] : before.split('\n')
  const b = after === '' ? [] : after.split('\n')
  const n = a.length
  const m = b.length
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const segs: DiffSegment[] = []
  let pending: { type: 'add' | 'del'; lines: string[] } | null = null
  const flush = () => {
    if (pending && pending.lines.length) segs.push(pending)
    pending = null
  }
  const push = (type: 'add' | 'del', line: string) => {
    if (!pending || pending.type !== type) {
      flush()
      pending = { type, lines: [] }
    }
    pending.lines.push(line)
  }

  let i = 0
  let j = 0
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) {
      flush()
      const last = segs[segs.length - 1]
      if (last && last.type === 'ctx') last.lines.push(a[i])
      else segs.push({ type: 'ctx', lines: [a[i]] })
      i++
      j++
    } else if (j === m || (i < n && dp[i + 1][j] >= dp[i][j + 1])) {
      push('del', a[i])
      i++
    } else if (j < m) {
      push('add', b[j])
      j++
    } else {
      break
    }
  }
  flush()
  return segs
}
