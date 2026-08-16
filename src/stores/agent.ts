import { defineStore } from 'pinia'
import {
  listAgents,
  createAgent,
  updateAgent,
  deleteAgent,
  publishAgent,
  unpublishAgent,
} from '@/api/agent'
import type { Agent, AgentConfigInput } from '@/types'

/** Agent store（docs/02 §7）：CRUD 后回刷列表 */
export const useAgentStore = defineStore('agent', {
  state: () => ({
    agents: [] as Agent[],
    loading: false,
  }),
  getters: {
    published: (s) => s.agents.filter((a) => a.status === 'published'),
  },
  actions: {
    async list() {
      this.loading = true
      try {
        const res = await listAgents({ page_size: 100 })
        this.agents = res.items
      } finally {
        this.loading = false
      }
    },
    async create(body: AgentConfigInput) {
      await createAgent(body)
      await this.list()
    },
    async update(id: string, body: AgentConfigInput) {
      await updateAgent(id, body)
      await this.list()
    },
    async remove(id: string) {
      await deleteAgent(id)
      await this.list()
    },
    async publish(id: string) {
      await publishAgent(id)
      await this.list()
    },
    async unpublish(id: string) {
      await unpublishAgent(id)
      await this.list()
    },
  },
})
