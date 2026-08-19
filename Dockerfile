# Agent 后端镜像（docs 05 §2.2，uv 版）：backend 与 worker 共用一个镜像，compose 用 command 区分入口。
# backend: uvicorn app.api.main:app
# worker : python -m app.worker
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1

WORKDIR /app

# 先装依赖（利用 Docker 层缓存：pyproject/uv.lock 变化才重装）
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

# 再拷源码与迁移
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./

EXPOSE 8000

# 默认 backend；启动前幂等迁移（alembic upgrade head 无变化时 no-op）
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.api.main:app --host 0.0.0.0 --port 8000"]
