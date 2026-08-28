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
    initialLoading: false,
    refreshing: false,
    loadingEarlier: false,
    error: false,
    errorMessage: null as string | null,
    requestVersion: 0,
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
      const initial = !this.detail || this.detail.conversation_id !== conversationId
      if (initial ? this.initialLoading : this.refreshing) return

      const requestVersion = ++this.requestVersion
      this.initialLoading = initial
      this.refreshing = !initial
      this.loading = true
      this.error = false
      this.errorMessage = null
      try {
        const res = await getTrajectory(conversationId)
        if (requestVersion !== this.requestVersion) return
        this.detail = { conversation_id: res.conversation_id, nodes: res.nodes }
        this.hasMore = !!res.has_more
      } catch {
        if (requestVersion !== this.requestVersion) return
        this.error = true
        this.errorMessage = '轨迹加载失败，请重试'
        // 刷新失败时保留现有轨迹，避免实时轮询短暂抹掉用户正在查看的内容。
        if (initial) {
          this.detail = null
          this.hasMore = false
        }
      } finally {
        if (requestVersion === this.requestVersion) {
          this.initialLoading = false
          this.refreshing = false
          this.loading = false
        }
      }
    },
    /** 加载更早一页（prepend 到 nodes 前） */
    async loadEarlier(conversationId: string) {
      if (this.unavailable || !this.detail || this.initialLoading || this.refreshing || this.loadingEarlier) return
      if (!this.detail.nodes.length) return
      const requestVersion = ++this.requestVersion
      const currentDetail = this.detail
      const minSeq = Math.min(...currentDetail.nodes.map((n) => n.seq))
      this.loadingEarlier = true
      this.loading = true
      this.error = false
      this.errorMessage = null
      try {
        const res = await getTrajectory(conversationId, { before_seq: minSeq })
        if (requestVersion !== this.requestVersion || !this.detail) return
        this.detail = {
          conversation_id: res.conversation_id,
          nodes: [...res.nodes, ...this.detail.nodes],
        }
        this.hasMore = !!res.has_more
      } catch {
        if (requestVersion === this.requestVersion) {
          this.error = true
          this.errorMessage = '加载更早轨迹失败，请重试'
        }
      } finally {
        if (requestVersion === this.requestVersion) {
          this.loadingEarlier = false
          this.loading = false
        }
      }
    },
    reset() {
      this.requestVersion += 1
      this.detail = null
      this.hasMore = false
      this.loading = false
      this.initialLoading = false
      this.refreshing = false
      this.loadingEarlier = false
      this.error = false
      this.errorMessage = null
    },
  },
})
