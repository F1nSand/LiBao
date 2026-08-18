import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useEvolutionStore } from './evolution'
import { FEATURE, markUnavailable, resetUnavailable } from '@/api/availability'

describe('evolution store 降级（后端未实现 /evolution → 404 打标）', () => {
  beforeEach(() => {
    resetUnavailable()
    setActivePinia(createPinia())
  })

  it('unavailable getter 随 FEATURE.evolution 打标翻转', () => {
    const store = useEvolutionStore()
    expect(store.unavailable).toBe(false)
    markUnavailable(FEATURE.evolution)
    expect(store.unavailable).toBe(true)
  })
})
