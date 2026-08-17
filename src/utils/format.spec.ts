import { describe, it, expect } from 'vitest'
import { formatBytes, formatDate, formatDuration, toolCallSummary, truncate } from './format'

describe('format 工具', () => {
  it('formatBytes', () => {
    expect(formatBytes(512)).toBe('512B')
    expect(formatBytes(2048)).toBe('2.0KB')
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0MB')
    expect(formatBytes(null)).toBe('-')
  })

  it('formatDate 容错', () => {
    expect(formatDate('2026-01-01T00:00:00Z')).toContain('2026')
    expect(formatDate(null)).toBe('-')
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })

  it('formatDuration', () => {
    expect(formatDuration(320)).toBe('320ms')
    expect(formatDuration(2500)).toBe('2.5s')
    expect(formatDuration(undefined)).toBe('-')
  })

  it('truncate', () => {
    expect(truncate('abc', 2)).toBe('ab…')
    expect(truncate('abc', 10)).toBe('abc')
    expect(truncate(null)).toBe('')
  })

  it('toolCallSummary 工具轮占位', () => {
    expect(toolCallSummary('calculator', { expression: '(3+4)*2-1' })).toBe('调用 calculator：(3+4)*2-1')
    expect(toolCallSummary('web_search', { query: '什么是 SSE', limit: 5 })).toBe('调用 web_search：什么是 SSE, 5')
    expect(toolCallSummary('time_now', '')).toBe('调用 time_now')
    expect(toolCallSummary('demo', { a: { b: 1 } })).toContain('调用 demo')
  })
})
