import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSkillStore } from './skill'
import { FEATURE, markUnavailable, resetUnavailable } from '@/api/availability'

describe('skill store 降级（后端未实现 /skills → 404 打标）', () => {
  beforeEach(() => {
    resetUnavailable()
    setActivePinia(createPinia())
  })

  it('unavailable getter 随 FEATURE.skills 打标翻转', () => {
    const store = useSkillStore()
    expect(store.unavailable).toBe(false)
    markUnavailable(FEATURE.skills)
    expect(store.unavailable).toBe(true)
  })
})
