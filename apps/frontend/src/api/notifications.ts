import { httpGet, httpPatch } from './http'
import type { Paged, Notification } from '@/types'

export function listNotifications(params: { page?: number; page_size?: number } = {}) {
  return httpGet<Paged<Notification>>('/notifications', { params })
}

export function markRead(id: string) {
  return httpPatch<Notification>(`/notifications/${id}/read`)
}
