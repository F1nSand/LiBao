import { defineStore } from 'pinia'
import { deleteMcpServer, listMcpServers, registerMcp } from '@/api/mcp'
import type { McpRegisterRequest, McpRegisterResult, McpServer } from '@/types'

type McpListStatus = 'idle' | 'loading' | 'success-empty' | 'success' | 'error'

export const useMcpStore = defineStore('mcp', {
  state: () => ({
    servers: [] as McpServer[],
    loading: false,
    status: 'idle' as McpListStatus,
    errorMessage: null as string | null,
    submitting: false,
  }),
  actions: {
    async list() {
      this.loading = true
      this.status = 'loading'
      this.errorMessage = null
      try {
        this.servers = await listMcpServers()
        this.status = this.servers.length ? 'success' : 'success-empty'
      } catch (e) {
        this.status = 'error'
        this.errorMessage = e instanceof Error ? e.message : 'MCP 服务列表加载失败'
      } finally {
        this.loading = false
      }
    },
    async retry() {
      await this.list()
    },
    async register(body: McpRegisterRequest): Promise<McpRegisterResult> {
      this.submitting = true
      try {
        const result = await registerMcp(body)
        await this.list()
        return result
      } finally {
        this.submitting = false
      }
    },
    async remove(id: string) {
      this.submitting = true
      try {
        await deleteMcpServer(id)
        await this.list()
      } finally {
        this.submitting = false
      }
    },
  },
})
