# LiBao Backend

FastAPI + LangGraph 后端。开发依赖由 uv 管理，入口为 `app.api.main:app`。

```text
uv sync
uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000
uv run ruff check .
uv run pytest tests/
```

配置使用用户目录 `~/.LiBao/settings.json`。详细说明见根目录 `docs/`。
