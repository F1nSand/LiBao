import type { Plugin } from 'vite'
import { mockServer } from './server'
import { setMockFast } from './util'

/**
 * Mock 适配层 Vite 插件（《02》接口契约 契约）：
 * dev 模式拦截 /api/v1/*，模拟 REST 信封与 SSE 事件流。
 * apply:'serve' → 生产构建不打包 mock。
 */
export function mockApiPlugin(): Plugin {
  return {
    name: 'mock-api',
    apply: 'serve',
    configResolved(config) {
      // e2e 模式（--mode e2e + VITE_MOCK_FAST=1）→ SSE 延迟归零，保证断言确定性
      setMockFast(config.mode === 'e2e' || config.env.VITE_MOCK_FAST === '1')
    },
    configureServer(server) {
      server.middlewares.use('/api/v1', (req, res, next) => {
        void mockServer.handle(req as never, res as never, next)
      })
    },
  }
}
