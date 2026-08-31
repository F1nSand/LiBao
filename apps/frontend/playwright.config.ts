import { defineConfig, devices } from '@playwright/test'

/**
 * e2e 依赖内置 mock 的确定性：webServer 以 `--mode e2e` 启动（VITE_USE_MOCK=true + VITE_MOCK_FAST=1）
 * E2E_PORT：5173 被占用时可在独立端口起干净 mock server（如 E2E_PORT=5199）。
 * 不复用已有 server，避免普通 dev server 的 mock 延迟/内存状态污染测试。
 */
const PORT = process.env.E2E_PORT ?? '5173'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'on-first-retry',
  },
  webServer: {
    command: `npm run dev -- --mode e2e --port ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
