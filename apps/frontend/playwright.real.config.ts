import { defineConfig, devices } from '@playwright/test'

/**
 * 真实后端 e2e：对接本机后端，抓前后端契约回归。
 * - 后端由根目录 scripts/test-real-e2e.* 管理；直接运行本配置时需先启动后端
 * - 前端以 `--mode real` 启动（VITE_USE_MOCK=false，vite 代理 /api → 后端）
 * - URL 通过 E2E_BACKEND_URL / E2E_FRONTEND_URL 配置，不依赖仓库目录结构
 * - 需在 `~/.LiBao/settings.json` 配好 LLM key；chat 用例走真实 LLM，耗时较长
 */
const BACKEND_URL = process.env.E2E_BACKEND_URL ?? 'http://127.0.0.1:8000'
const FRONTEND_URL = process.env.E2E_FRONTEND_URL ?? 'http://127.0.0.1:5173'

export default defineConfig({
  testDir: './e2e-real',
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: FRONTEND_URL,
    trace: 'on-first-retry',
  },
  webServer: {
    command: `npm run dev -- --mode real --host 127.0.0.1 --port ${new URL(FRONTEND_URL).port || '5173'}`,
    url: FRONTEND_URL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
