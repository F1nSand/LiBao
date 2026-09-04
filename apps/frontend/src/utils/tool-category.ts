import type { ToolDefinition } from '@/types'

export type ToolCategory = 'mcp' | 'meta' | 'regular'

/** 工具页展示分类：MCP 来源优先于平台元工具标记。 */
export function getToolCategory(tool: Pick<ToolDefinition, 'mcp_source' | 'meta'>): ToolCategory {
  if (tool.mcp_source?.trim()) return 'mcp'
  return tool.meta ? 'meta' : 'regular'
}
