import { defineStore } from 'pinia'
import {
  listTools,
  toggleTool,
  createTool,
  updateTool,
  deleteTool,
  testTool,
  searchTools,
} from '@/api/tool'
import type { CreateToolRequest, ToolDefinition, ToolSearchHit } from '@/types'

type ToolListStatus = 'idle' | 'loading' | 'success-empty' | 'success' | 'error'

export interface ToggleManyResult {
  succeeded: ToolDefinition[]
  failed: Array<{ id: string; reason: unknown }>
}

/** 工具 store（《02》前端设计 §7）：列表 + 启用开关 + 测试结果 */
export const useToolStore = defineStore('tool', {
  state: () => ({
    tools: [] as ToolDefinition[],
    loading: false,
    status: 'idle' as ToolListStatus,
    errorMessage: null as string | null,
  }),
  actions: {
    async list() {
      this.loading = true
      this.status = 'loading'
      this.errorMessage = null
      try {
        const res = await listTools({ page_size: 100 })
        this.tools = res.items
        this.status = this.tools.length ? 'success' : 'success-empty'
      } catch (e) {
        this.status = 'error'
        this.errorMessage = e instanceof Error ? e.message : '工具列表加载失败'
      } finally {
        this.loading = false
      }
    },
    async retry() {
      await this.list()
    },
    async toggle(id: string, enabled: boolean) {
      const updated = await toggleTool(id, enabled)
      const index = this.tools.findIndex((tool) => tool.id === id)
      if (index >= 0) this.tools.splice(index, 1, updated)
      return updated
    },
    async toggleMany(ids: string[], enabled: boolean): Promise<ToggleManyResult> {
      const settled = await Promise.allSettled(ids.map((id) => this.toggle(id, enabled)))
      const succeeded: ToolDefinition[] = []
      const failed: Array<{ id: string; reason: unknown }> = []
      settled.forEach((result, index) => {
        if (result.status === 'fulfilled') succeeded.push(result.value)
        else failed.push({ id: ids[index], reason: result.reason })
      })
      return { succeeded, failed }
    },
    async create(body: CreateToolRequest) {
      await createTool(body)
      await this.list()
    },
    async update(id: string, body: Partial<CreateToolRequest>) {
      await updateTool(id, body)
      await this.list()
    },
    async remove(id: string) {
      await deleteTool(id)
      await this.list()
    },
    async test(id: string, params: Record<string, unknown>) {
      return testTool(id, params)
    },
    async search(q: string): Promise<ToolSearchHit[]> {
      return searchTools(q)
    },
  },
})
