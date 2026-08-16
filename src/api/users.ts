import { httpGet, httpPost, httpPatch, httpDelete } from './http'
import type { Paged, User, CreateUserRequest, Role } from '@/types'

export function listUsers(params: { page?: number; page_size?: number } = {}) {
  return httpGet<Paged<User>>('/users', { params })
}

export function createUser(body: CreateUserRequest) {
  return httpPost<User>('/users', body)
}

export function patchUserRole(id: string, role: Role) {
  return httpPatch<User>(`/users/${id}/role`, { role })
}

export function patchUserStatus(id: string, enabled: boolean) {
  return httpPatch<User>(`/users/${id}/status`, { enabled })
}

export function deleteUser(id: string) {
  return httpDelete<null>(`/users/${id}`)
}
