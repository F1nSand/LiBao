import { httpGet, httpPost, httpDelete } from './http'
import type { RegisterHookRequest, WebhookConfig } from '@/types'

/** Webhook 管理（docs/03 §5.10）：注册/列表/删除；公开 receive 供外部系统调用，不进管理 UI */
export function listHooks() {
  return httpGet<WebhookConfig[]>('/hooks')
}

export function registerHook(toolId: string, body: RegisterHookRequest) {
  return httpPost<WebhookConfig>(`/hooks/${toolId}/register`, body)
}

export function unregisterHook(toolId: string) {
  return httpDelete<null>(`/hooks/${toolId}`)
}
