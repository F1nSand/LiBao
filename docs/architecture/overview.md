# 架构总览

LiBao 的运行链路是：浏览器 → Vue/Vite → FastAPI → LangGraph 编排 → 服务与工具 → 本地 FileStore、JSONL、LanceDB 和工作区文件。

```text
apps/frontend  ── REST/SSE /api/v1 ──>  apps/backend
      │                                      │
      └── Mock API（开发/E2E）                ├── api
                                             ├── orchestration
                                             ├── services / tools
                                             └── storage / core
```

后端保持 API → 编排 → 服务 → 工具 → 存储的单向依赖意图。前端以路由页面、领域状态、API 封装和可复用组件分层。DevPanel 只负责本地进程监管，不参与业务请求。

当前采用本地单用户模式：运行数据默认位于 `~/.LiBao`，后端通过 `app.api.main:app` 暴露 ASGI 应用，前端生产构建可由 Nginx 或后端静态托管参考配置提供。
