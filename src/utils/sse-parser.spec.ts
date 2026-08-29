import { describe, it, expect } from 'vitest'
import { SseParser, parseSseFrame, SeqGuard } from './sse-parser'

function env(type: string, seq: number, text: string) {
  return JSON.stringify({ id: `evt_${seq}`, seq, type, ts: 1700000000000 + seq, payload: { text } })
}

describe('parseSseFrame', () => {
  it('解析单帧 event:/data:', () => {
    const frame = `event: token\ndata: ${env('token', 1, '你好')}`
    const ev = parseSseFrame(frame)
    expect(ev).not.toBeNull()
    expect(ev!.type).toBe('token')
    expect(ev!.seq).toBe(1)
    expect((ev!.payload as { text: string }).text).toBe('你好')
  })

  it('data 多行以 \\n 拼接（标准 SSE）', () => {
    const frame = `event: done\ndata: ${env('done', 2, '')}`
    const ev = parseSseFrame(frame)
    expect(ev!.type).toBe('done')
  })

  it('keepalive 注释行（:）返回 null', () => {
    expect(parseSseFrame(': keepalive\n\n')).toBeNull()
    expect(parseSseFrame('')).toBeNull()
  })

  it('损坏 JSON 返回 null（容错丢帧）', () => {
    expect(parseSseFrame('event: token\ndata: {oops}')).toBeNull()
  })

  it('CRLF 与 LF 一致', () => {
    const lf = parseSseFrame(`event: token\ndata: ${env('token', 1, 'a')}`)
    const crlf = parseSseFrame(`event: token\r\ndata: ${env('token', 1, 'a')}\r\n`)
    expect(lf).toEqual(crlf)
  })

  it('信封含 task_seq 时透传；缺省为 undefined（旧后端兼容）', () => {
    const withTs = parseSseFrame(`event: token\ndata: ${JSON.stringify({ id: 'e1', seq: 1, task_seq: 7, type: 'token', ts: 1, payload: { text: 'x' } })}`)
    expect(withTs!.task_seq).toBe(7)
    const without = parseSseFrame(`event: token\ndata: ${env('token', 1, 'x')}`)
    expect(without!.task_seq).toBeUndefined()
  })
})

describe('SseParser 增量解析', () => {
  it('chunk 跨帧边界拼包', () => {
    const p = new SseParser()
    const a = `event: token\ndata: ${env('token', 1, 'a')}\n\nevent: token`
    const b = `\ndata: ${env('token', 2, 'b')}\n\n`
    expect(p.push(a)).toHaveLength(1)
    expect(p.push(b)).toHaveLength(1)
    expect(p.end()).toHaveLength(0)
  })

  it('帧内残留未闭合时不产出事件，end() 冲刷', () => {
    const p = new SseParser()
    expect(p.push(`event: token\ndata: ${env('token', 3, 'c')}`)).toHaveLength(0)
    const rest = p.end()
    expect(rest).toHaveLength(1)
    expect(rest[0].seq).toBe(3)
  })
})

describe('SeqGuard', () => {
  it('拒绝重复与乱序 seq', () => {
    const g = new SeqGuard()
    expect(g.accept(1)).toBe(true)
    expect(g.accept(1)).toBe(false) // 重复
    expect(g.accept(0)).toBe(false) // 乱序
    expect(g.accept(2)).toBe(true)
    expect(g.accept(5)).toBe(true)
  })

  it('current() 返回已接受的最大 seq', () => {
    const g = new SeqGuard()
    expect(g.current()).toBe(-1)
    g.accept(3)
    expect(g.current()).toBe(3)
  })
})
