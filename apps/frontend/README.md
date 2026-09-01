# LiBao Frontend

Vue 3 + TypeScript + Vite 前端工作台。

```text
npm ci
npm run dev                 # 真实本地后端；Vite /api 代理到 127.0.0.1:8000
npm run lint:check
npm run typecheck
npm run test:unit
npm run test:e2e
```

Mock 仅用于单测和 Mock E2E；需要隔离后端时使用 Playwright 的 `--mode e2e`。真实后端 E2E 由根目录 `scripts/test-real-e2e.*` 管理。
