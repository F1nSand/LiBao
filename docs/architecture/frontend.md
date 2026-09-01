# 前端结构

入口链路是 `index.html` → `src/main.ts` → `App.vue` → `src/router` → `src/views`。

当前前端包含：

- `src/api`：Axios、REST、SSE、任务控制和接口可用性；
- `src/stores`：Pinia 领域状态；
- `src/composables`：流式聊天、任务轮询、响应式状态；
- `src/components`：通用、布局、业务、工作区和轨迹组件；
- `src/mock`：Vite middleware、内存数据和确定性 SSE；
- `e2e`：Mock Playwright；`e2e-real`：本地真实后端契约测试。

正常开发由 DevPanel 启动真实后端，Vite 将相对路径 `/api` 代理到 `VITE_API_PROXY`；发布时浏览器直接访问 FastAPI 提供的 SPA。Mock 仅用于单测和 Mock E2E，后者使用 `--mode e2e`，不需要后端。
