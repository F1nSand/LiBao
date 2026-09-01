# 架构总览

LiBao 的运行链路是：浏览器 → Vue/Vite → FastAPI → LangGraph 编排 → 服务与工具 → 本地 FileStore、JSONL、LanceDB 和工作区文件。

```text
开发：浏览器 :5173 ── /api（Vite 代理）──> FastAPI :8000
发布：浏览器 :8000 ── REST/SSE + SPA ──> FastAPI

apps/frontend  ── REST/SSE /api/v1 ──>  apps/backend
      │                                      │
      └── Mock API（单测/Mock E2E）             ├── api
                                             ├── orchestration
                                             ├── services / tools
                                             └── storage / core
```

后端保持 API → 编排 → 服务 → 工具 → 存储的单向依赖意图。前端以路由页面、领域状态、API 封装和可复用组件分层。DevPanel 只负责本地进程监管，不参与业务请求。

当前采用永久本地单用户模式：运行数据默认位于 `~/.LiBao`，固定用户为 `admin`，后端通过 `app.api.main:app` 暴露 ASGI 应用。发布时只启动后端，由后端静态托管前端构建物；`deploy/` 仅保存沙箱参考配置。
