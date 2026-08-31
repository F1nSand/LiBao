import axios from 'axios'
import { httpGet, httpPost, ApiError } from './http'
import type { Task } from '@/types'

export type CancelTaskResult = 'cancelled' | 'already-finished'

export interface RecoverTaskResult {
  task_id: string
  status: string
}

export async function getTaskStatus(taskId: string): Promise<Task> {
  return httpGet<Task>(`/tasks/${encodeURIComponent(taskId)}`)
}

/** 取消正在运行的聊天/任务；40902 表示与完成事件竞争成功，交由 SSE 收敛最终状态。 */
export async function cancelTask(taskId: string): Promise<CancelTaskResult> {
  try {
    await httpPost<null>(`/tasks/${taskId}/cancel`)
    return 'cancelled'
  } catch (error) {
    const code = error instanceof ApiError
      ? error.code
      : axios.isAxiosError(error)
        ? Number((error.response?.data as { code?: number } | undefined)?.code)
        : undefined
    if (code === 40902) return 'already-finished'
    throw error
  }
}

/** 从断点继续：仅 failed+recoverable 且 recovery_attempts<3；幂等 key 缺省 uuid4。 */
export async function recoverTask(taskId: string, idempotencyKey: string = crypto.randomUUID()): Promise<RecoverTaskResult> {
  return httpPost<RecoverTaskResult>(`/tasks/${encodeURIComponent(taskId)}/recover`, {
    idempotency_key: idempotencyKey,
  })
}
