import { defineStore } from 'pinia'
import { getTrajectory } from '@/api/trajectory'
import { FEATURE, isUnavailable } from '@/api/availability'
import type { TrajectoryDetail } from '@/types'

/** trajectory store（docs/02 §6.3）：按会话隔离的只读轨迹；支持「加载更早」分页累积 */
export const useTrajectoryStore = defineStore('trajectory', {
  state: () => ({
    detail: null as TrajectoryDetail | null,
    hasMore: false,
    loading: false,
    error: false,
  }),
  getters: {
    /** 后端未实现轨迹接口（HTTP 404 打标）→ 页面显示空态 */
    unavailable: () => isUnavailable(FEATURE.trajectory),
  },
  actions: {
    /** 初始加载（最近一页） */
    async load(conversationId: string) {
      // 已确认未实现 → 不重复请求，直接空态
      if (this.unavailable) {
        this.reset()
        return
      }
      this.loading = true
      this.error = false
      try {
        const res = await getTrajectory(conversationId)
        this.detail = { conversation_id: res.conversation_id, nodes: res.nodes }
        this.hasMore = !!res.has_more
      } catch {
        this.error = true
        this.detail = null
        this.hasMore = false
      } finally {
        this.loading = false
      }
    },
    /** 加载更早一页（prepend 到 nodes 前） */
    async loadEarlier(conversationId: string) {
      if (this.unavailable || !this.detail) return
      const minSeq = Math.min(...this.detail.nodes.map((n) => n.seq))
      this.loading = true
      try {
        const res = await getTrajectory(conversationId, { before_seq: minSeq })
        this.detail = {
          conversation_id: res.conversation_id,
          nodes: [...res.nodes, ...this.detail.nodes],
        }
        this.hasMore = !!res.has_more
      } finally {
        this.loading = false
      }
    },
    reset() {
      this.detail = null
      this.hasMore = false
      this.loading = false
      this.error = false
    },
  },
})
