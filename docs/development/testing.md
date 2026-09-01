# 测试指南

后端：

```text
cd apps/backend
uv sync --frozen
uv run ruff check .
uv run pytest tests/
```

前端：

```text
cd apps/frontend
npm ci
npm run lint:check
npm run typecheck
npm run build
npm run test:unit
npm run test:e2e
```

正常开发配置：`.env.local` 中使用 `VITE_USE_MOCK=false`，并用 `VITE_API_PROXY` 指向本机后端（默认 `http://127.0.0.1:8000`）。`E2E_PORT` 只用于 Mock Playwright，`E2E_BACKEND_URL` 和 `E2E_FRONTEND_URL` 只用于真实后端 E2E；真实 runner 会校验它们只能是 `http://127.0.0.1:<port>`。

真实后端 E2E 可运行 `scripts/test-real-e2e.cmd` 或 `scripts/test-real-e2e.sh`，也可先设置 `E2E_BACKEND_URL=http://127.0.0.1:18000`、`E2E_FRONTEND_URL=http://127.0.0.1:15173`。测试可能访问配置的 LLM 服务，只能本地或手动运行，不读取 CI 中的 LLM 密钥。任何路径迁移后都要执行一次全新 clone 验证。
