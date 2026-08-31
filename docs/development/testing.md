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

真实后端 E2E 需要先启动后端，并设置 `E2E_BACKEND_URL`；测试可能访问配置的 LLM 服务，只能本地或手动运行。任何路径迁移后都要执行一次全新 clone 验证。
