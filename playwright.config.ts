import { defineConfig, devices } from '@playwright/test'

/**
 * e2e 依赖内置 mock 的确定性：webServer 以 `--mode e2e` 启动（VITE_USE_MOCK=true + VITE_MOCK_FAST=1）
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run dev -- --mode e2e',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
