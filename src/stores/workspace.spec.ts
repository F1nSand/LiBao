import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkspaceStore } from './workspace'
import { FEATURE, markUnavailable, resetUnavailable } from '@/api/availability'

describe('workspace store 降级（后端未实现 /workspaces → 404 打标）', () => {
  beforeEach(() => {
    resetUnavailable()
    setActivePinia(createPinia())
  })

  it('unavailable getter 随 FEATURE.workspaces 打标翻转', () => {
    const store = useWorkspaceStore()
    expect(store.unavailable).toBe(false)
    markUnavailable(FEATURE.workspaces)
    expect(store.unavailable).toBe(true)
  })
})
