import type { SseEnvelope } from '@/types'

/**
 * 任务事件日志 + live-tail 订阅总线（mock 版 JSONL）。
 * - persist 事件（业务边界事件）追加日志，供 GET /tasks/:id/events?after_seq=N 补发；
 * - 非 persist 事件（token/thinking）只广播给当前订阅者；
 * - task_seq 跨连接单调递增（对应真实后端 Task.last_event_seq）。
 */

export interface LoggedTaskEvent {
  task_seq: number
  envelope: SseEnvelope
}

const logs = new Map<string, LoggedTaskEvent[]>()
const seqCounters = new Map<string, number>()
const subscribers = new Map<string, Set<(ev: SseEnvelope) => void>>()

/** task_seq 单调递增并返回（发送 persist 事件前调用） */
export function nextTaskSeq(taskId: string): number {
  const next = (seqCounters.get(taskId) ?? 0) + 1
  seqCounters.set(taskId, next)
  return next
}

/** 当前 task_seq 水位（GET /tasks/:id 的 last_event_seq） */
export function taskLastSeq(taskId: string): number {
  return seqCounters.get(taskId) ?? 0
}

/** 发布事件：persist=true 追加日志（供补发）+ 广播；否则仅广播 live-tail */
export function pushTaskEvent(taskId: string, env: SseEnvelope, persist: boolean): void {
  let framed = env
  if (persist) {
    const seq = env.task_seq ?? nextTaskSeq(taskId)
    framed = { ...env, task_seq: seq }
    const list = logs.get(taskId) ?? []
    list.push({ task_seq: seq, envelope: framed })
    logs.set(taskId, list)
  }
  const subs = subscribers.get(taskId)
  if (subs) for (const fn of subs) fn(framed)
}

/** 补发 task_seq > afterSeq 的持久化事件 */
export function replayTaskEvents(taskId: string, afterSeq: number): SseEnvelope[] {
  return (logs.get(taskId) ?? []).filter((e) => e.task_seq > afterSeq).map((e) => e.envelope)
}

/** 订阅 live-tail，返回退订函数 */
export function subscribeTaskLog(taskId: string, fn: (ev: SseEnvelope) => void): () => void {
  let set = subscribers.get(taskId)
  if (!set) {
    set = new Set()
    subscribers.set(taskId, set)
  }
  set.add(fn)
  return () => {
    set.delete(fn)
    if (set.size === 0) subscribers.delete(taskId)
  }
}
