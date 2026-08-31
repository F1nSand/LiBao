// Vitest 全局 stub：jsdom 缺失的浏览器 API
import { vi } from 'vitest'

// ResizeObserver（useVirtualList 依赖）
if (!('ResizeObserver' in globalThis)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver
}

// matchMedia（Element Plus 响应式）
if (!('matchMedia' in globalThis)) {
  globalThis.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

// scrollTo（部分组件）
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {}
}
