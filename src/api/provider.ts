import { httpGet, httpPost, httpPatch, httpDelete } from './http'
import type { ProviderConfig, SaveProviderRequest } from '@/types'

/**
 * Provider 配置（前端定义契约，docs 03 §5.6）：
 * GET/POST /settings/providers、PATCH/DELETE /settings/providers/{id}。
 * api_key 只写不读（响应仅 has_key 标记）；后端已实现，availability 降级仅兜底。
 */
export function listProviders() {
  return httpGet<ProviderConfig[]>('/settings/providers')
}

export function createProvider(body: SaveProviderRequest) {
  return httpPost<ProviderConfig>('/settings/providers', body)
}

export function updateProvider(id: string, body: Partial<SaveProviderRequest>) {
  return httpPatch<ProviderConfig>(`/settings/providers/${id}`, body)
}

export function deleteProvider(id: string) {
  return httpDelete<null>(`/settings/providers/${id}`)
}
