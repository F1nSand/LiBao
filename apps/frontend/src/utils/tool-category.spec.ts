import { describe, expect, it } from 'vitest'
import type { ToolDefinition } from '@/types'
import { getToolCategory } from './tool-category'

const tool = (overrides: Partial<Pick<ToolDefinition, 'mcp_source' | 'meta'>> = {}) =>
  ({ mcp_source: null, meta: false, ...overrides }) as Pick<ToolDefinition, 'mcp_source' | 'meta'>

describe('getToolCategory', () => {
  it('按 MCP、元工具、常规工具的优先级返回互斥分类', () => {
    expect(getToolCategory(tool({ mcp_source: 'mcp:server-1' }))).toBe('mcp')
    expect(getToolCategory(tool({ meta: true }))).toBe('meta')
    expect(getToolCategory(tool())).toBe('regular')
  })

  it('MCP 来源优先于 meta 标记', () => {
    expect(getToolCategory(tool({ mcp_source: 'mcp:server-1', meta: true }))).toBe('mcp')
    expect(getToolCategory(tool({ mcp_source: '  mcp:server-1  ' }))).toBe('mcp')
    expect(getToolCategory(tool({ mcp_source: '   ' }))).toBe('regular')
  })
})
