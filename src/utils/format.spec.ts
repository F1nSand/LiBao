import { describe, it, expect } from 'vitest'
import { formatBytes, formatDate, formatDuration, truncate } from './format'

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
})
