import { httpGet } from './http'
import type { TrajectoryDetail } from '@/types'

/** 对话轨迹（《02》接口契约 §5.2.x）：按会话隔离的只读轨迹；before_seq/limit 分页加载更早 */
export function getTrajectory(
  conversationId: string,
  params: { before_seq?: number; limit?: number } = {},
) {
  return httpGet<TrajectoryDetail>(`/conversations/${conversationId}/trajectory`, { params })
}
