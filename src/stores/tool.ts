import { defineStore } from 'pinia'
import {
  listTools,
  toggleTool,
  createTool,
  updateTool,
  deleteTool,
  testTool,
  registerMcp,
  searchTools,
} from '@/api/tool'
import type { CreateToolRequest, ToolDefinition, ToolSearchHit } from '@/types'

type ToolListStatus = 'idle' | 'loading' | 'success-empty' | 'success' | 'error'

/** 工具 store（docs/02 §7）：列表 + 启用开关 + 测试结果 */
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
      await toggleTool(id, enabled)
      await this.list()
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
    async registerMcp(url: string, headers?: Record<string, string>) {
      await registerMcp({ url_or_command: url, headers })
      await this.list()
    },
    async search(q: string): Promise<ToolSearchHit[]> {
      return searchTools(q)
    },
  },
})
