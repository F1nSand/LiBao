import { httpPost, httpGet } from './http'
import type { LoginRequest, LoginResponse, User } from '@/types'

export function login(p: LoginRequest) {
  return httpPost<LoginResponse>('/auth/login', p)
}

export function logout() {
  return httpPost<null>('/auth/logout')
}

export function me() {
  return httpGet<User>('/auth/me')
}
