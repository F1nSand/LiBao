import { httpGet, httpPost } from './http'
import type { Paged, Task, SubmitTaskRequest } from '@/types'

export function submitTask(body: SubmitTaskRequest) {
  return httpPost<{ task_id: string }>('/tasks', body)
}

export function listTasks(params: { page?: number; page_size?: number; status?: string } = {}) {
  return httpGet<Paged<Task>>('/tasks', { params })
}

export function getTask(id: string) {
  return httpGet<Task>(`/tasks/${id}`)
}

export function cancelTask(id: string) {
  return httpPost<null>(`/tasks/${id}/cancel`)
}

export function resumeTask(id: string, confirm: Record<string, unknown> | null) {
  return httpPost<null>(`/tasks/${id}/resume`, { confirm })
}
