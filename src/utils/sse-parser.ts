import type { SseEnvelope, SseEventType } from '@/types'

/**
 * SSE 逐帧解析器（docs/03 §3）。
 * 纯函数 + 增量状态，便于单测；多字节 UTF-8 由调用方用 TextDecoder({stream:true}) 保证不截断。
 */

/** 单帧解析：event:/data:/id:/retry:，注释行(:)跳过；data JSON 解析失败返回 null（容错丢帧） */
export function parseSseFrame(frame: string): SseEnvelope | null {
  let event: string | undefined
  let id: string | undefined
  const data: string[] = []

  for (const raw of frame.split('\n')) {
    const line = raw.trimEnd()
    if (line === '' || line.startsWith(':')) continue // 空行 / keepalive 注释
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data.push(line.slice(5).replace(/^ /, ''))
    } else if (line.startsWith('id:')) {
      id = line.slice(3).trim()
    } else if (line.startsWith('retry:')) {
      // 忽略 retry 指令
    }
  }

  if (data.length === 0) return null

  const raw = data.join('\n')
  try {
    const parsed = JSON.parse(raw) as Partial<SseEnvelope> & { type?: string }
    // 以 data 信封为准（含 id/seq/type/ts/payload）；缺省用 event: 字段兜底
    return {
      id: (parsed.id as string) ?? id ?? '',
      seq: typeof parsed.seq === 'number' ? parsed.seq : -1,
      task_seq: typeof parsed.task_seq === 'number' ? parsed.task_seq : undefined,
      type: (parsed.type as SseEventType) ?? (event as SseEventType) ?? 'token',
      ts: typeof parsed.ts === 'number' ? parsed.ts : Date.now(),
      payload: parsed.payload ?? parsed,
    } as SseEnvelope
  } catch {
    return null // 损坏帧跳过，不崩流
  }
}

/** 增量状态：按空行分帧，末段留 buffer */
export class SseParser {
  private buffer = ''

  push(chunk: string): SseEnvelope[] {
    this.buffer += chunk.replace(/\r\n/g, '\n')
    const events: SseEnvelope[] = []
    let idx: number
    while ((idx = this.buffer.indexOf('\n\n')) !== -1) {
      const frame = this.buffer.slice(0, idx)
      this.buffer = this.buffer.slice(idx + 2)
      const ev = parseSseFrame(frame)
      if (ev) events.push(ev)
    }
    return events
  }

  /** 流结束时冲刷残留 buffer */
  end(): SseEnvelope[] {
    if (!this.buffer.trim()) {
      this.buffer = ''
      return []
    }
    const ev = parseSseFrame(this.buffer)
    this.buffer = ''
    return ev ? [ev] : []
  }
}

/** seq 去重：只接受单调递增的 seq */
export class SeqGuard {
  private last = -1

  accept(seq: number): boolean {
    if (seq <= this.last) return false
    this.last = seq
    return true
  }

  /** 本连接内已交付的最大 seq（断线诊断用） */
  current(): number {
    return this.last
  }
}
