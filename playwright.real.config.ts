import { defineConfig, devices } from '@playwright/test'

/**
 * 真实后端 e2e：对接本机后端（127.0.0.1:8000），抓前后端契约回归。
 * - 前端以 `--mode real` 启动（VITE_USE_MOCK=false，vite 代理 /api → 后端）
 * - 后端 webServer 启动 uvicorn；已运行则复用（reuseExistingServer）
 * - 需 `.env`（后端）配好 DeepSeek/SiliconFlow key；chat 用例走真实 LLM，耗时较长
 */
export default defineConfig({
  testDir: './e2e-real',
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  webServer: [
    {
      command: 'cd ..\\Agent && uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000',
      url: 'http://127.0.0.1:8000/api/v1/system/health',
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --mode real',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
