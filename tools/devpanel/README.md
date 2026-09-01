# DevPanel

本地开发服务监管面板，负责启动、停止和查看 `apps/backend`、`apps/frontend` 的状态与日志。它不是生产服务，也不参与业务 API。DevPanel 默认启动真实后端；Mock 只用于单测和 Mock E2E。

```text
uv sync
uv run python main.py
```

默认端口为后端 `127.0.0.1:8000`、前端 `127.0.0.1:5173`、面板 `127.0.0.1:9100`。可使用 `LIBAO_BACKEND_PORT`、`LIBAO_FRONTEND_PORT`、`LIBAO_DEVPANEL_PORT` 同时改动对应服务；前端的 `VITE_API_PROXY` 会自动指向后端端口。所有服务只绑定回环地址。
