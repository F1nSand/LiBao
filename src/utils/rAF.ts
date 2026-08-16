/** rAF 合并渲染（docs/02 §5.4.4 J6）：一帧内多个 token 合并为一次 DOM 更新 */

type Fn = () => void

let pending: Fn[] = []
let scheduled = false

function flush(): void {
  scheduled = false
  const fns = pending
  pending = []
  for (const fn of fns) fn()
}

export function throttleByRaf(fn: Fn): () => void {
  return () => {
    pending.push(fn)
    if (!scheduled) {
      scheduled = true
      requestAnimationFrame(flush)
    }
  }
}

/** 流结束时同步冲刷未提交的帧（done/stop 场景） */
export function flushNow(): void {
  if (scheduled) flush()
}
