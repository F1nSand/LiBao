import { describe, it, expect } from 'vitest'
import { canAccess } from './guard'
import type { Role } from '@/types'

describe('canAccess 角色守卫', () => {
  it('requiresAuth 为 false → 公开可访问', () => {
    expect(canAccess({ requiresAuth: false }, 'viewer')).toBe(true)
  })

  it('requiresAuth 无 roles 限制 → 已登录即可（含 user 未加载时 role=undefined，防守卫循环）', () => {
    expect(canAccess({ requiresAuth: true }, undefined)).toBe(true)
    expect(canAccess({ requiresAuth: true }, 'viewer')).toBe(true)
  })

  it('roles 限制且未登录（role=undefined）→ 不可访问', () => {
    const meta = { requiresAuth: true, roles: ['admin'] as Role[] }
    expect(canAccess(meta, undefined)).toBe(false)
  })

  it('/agents 类（developer+）拦截 viewer', () => {
    const meta: { requiresAuth: true; roles: Role[] } = { requiresAuth: true, roles: ['admin', 'developer'] }
    expect(canAccess(meta, 'viewer')).toBe(false)
    expect(canAccess(meta, 'developer')).toBe(true)
    expect(canAccess(meta, 'admin')).toBe(true)
  })

  it('/system 类（admin）拦截 developer', () => {
    const meta: { requiresAuth: true; roles: Role[] } = { requiresAuth: true, roles: ['admin'] }
    expect(canAccess(meta, 'developer')).toBe(false)
    expect(canAccess(meta, 'admin')).toBe(true)
  })
})
