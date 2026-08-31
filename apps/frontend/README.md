# LiBao Frontend

Vue 3 + TypeScript + Vite 前端工作台。

```text
npm ci
npm run dev                 # 默认 Mock
npm run lint:check
npm run typecheck
npm run test:unit
npm run test:e2e
```

设置 `VITE_USE_MOCK=false` 后，`/api` 通过 `VITE_API_PROXY` 访问后端。
