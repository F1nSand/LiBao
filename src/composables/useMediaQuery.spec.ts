import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { useMediaQuery } from './useMediaQuery'

/** 可控 matchMedia mock：可改 matches 并触发 change 监听 */
function installMatchMedia(initial: boolean) {
  const listeners = new Set<(e: MediaQueryListEvent) => void>()
  const mql = {
    matches: initial,
    media: '(max-width: 960px)',
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn((_t: string, cb: (e: MediaQueryListEvent) => void) => listeners.add(cb)),
    removeEventListener: vi.fn((_t: string, cb: (e: MediaQueryListEvent) => void) => listeners.delete(cb)),
    dispatchEvent: vi.fn(),
  }
  vi.stubGlobal('matchMedia', vi.fn(() => mql))
  return {
    setMatches(v: boolean) {
      mql.matches = v
      listeners.forEach((cb) => cb({ matches: v } as MediaQueryListEvent))
    },
    listenerCount: () => listeners.size,
  }
}

const Comp = defineComponent({
  props: { query: { type: String, default: '(max-width: 960px)' } },
  setup(props) {
    const isActive = useMediaQuery(props.query)
    return { isActive }
  },
  template: `<div></div>`,
})

afterEach(() => vi.unstubAllGlobals())

describe('useMediaQuery', () => {
  it('初始 matches 反映到 isActive', () => {
    installMatchMedia(true)
    const w = mount(Comp)
    expect(w.vm.isActive).toBe(true)
    w.unmount()
  })

  it('change 事件触发时更新 isActive（窄↔宽来回）', () => {
    const mq = installMatchMedia(false)
    const w = mount(Comp)
    expect(w.vm.isActive).toBe(false)
    mq.setMatches(true)
    expect(w.vm.isActive).toBe(true)
    mq.setMatches(false)
    expect(w.vm.isActive).toBe(false)
    w.unmount()
  })

  it('组件卸载时移除 change 监听', () => {
    const mq = installMatchMedia(true)
    const w = mount(Comp)
    expect(mq.listenerCount()).toBe(1)
    w.unmount()
    expect(mq.listenerCount()).toBe(0)
  })
})
