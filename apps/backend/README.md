# LiBao Backend

FastAPI + LangGraph 后端。开发依赖由 uv 管理，入口为 `app.api.main:app`。

```text
uv sync
uv run python scripts/start_backend.py
uv run ruff check .
uv run pytest tests/
```

后端固定绑定 `127.0.0.1`，并通过 `LIBAO_BACKEND_PORT` 或 `--port` 选择端口。发布包中 FastAPI 同时提供 REST/SSE 和前端 SPA。配置唯一使用用户目录 `~/.LiBao/settings.json`。详细说明见根目录 `docs/`。
