"""应用工厂（docs 01 §5.1）。create_app + lifespan + trace_id 中间件 + 统一异常 → 信封。

Windows 关键：psycopg async 需 SelectorEventLoop，而 Windows 默认 ProactorEventLoop 不兼容；
在模块顶层设置策略，使 uvicorn 创建事件循环时即用 Selector（langgraph AsyncPostgresSaver 依赖）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.envelope import fail
from app.api.routers import (
    attachments,
    chat,
    checkpoints,
    conversations,
    kb,
    memory,
    notifications,
    skills,
    system,
    tasks,
    tools,
    workspaces,
)
from app.api.routers import (
    settings as settings_router,
)
from app.core.bootstrap import cleanup_runtime, init_runtime
from app.core.config import get_settings
from app.core.errors import ERR_INTERNAL, AppError, http_status_for
from app.core.logging import set_trace_id, setup_logging
from app.orchestration.checkpointer import build_checkpointer
from app.orchestration.graph import build_graph

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    runtime = await init_runtime(settings)
    app.state.store = runtime.store
    # 本地单机化：JsonFileSaver（.agent/checkpoints/），resume 语义与 PostgresSaver 等价
    saver = build_checkpointer(settings)
    app.state.checkpointer = saver
    app.state.graph = build_graph(saver)
    # 临时会话工作区 TTL 清理（后台周期任务，删 cache/sessions/* 过期目录）
    from app.checkpoints.runtime import get_checkpoint_service
    from app.core.session_cache import session_cache_loop

    checkpoint_service = get_checkpoint_service(settings.agent_data_dir, settings.checkpoint_retention_days)
    recovered = await checkpoint_service.recover_open_checkpoints()
    if recovered:
        logger.info("checkpoint crash recovery: marked %d open manifests interrupted", recovered)
    recovered_operations = await checkpoint_service.recover_incomplete_operations()
    if recovered_operations:
        logger.info("rollback operation recovery: marked %d incomplete journals failed_partial", recovered_operations)
    from app.services.task_recovery import reconcile_orphaned_tasks

    task_recovery = await reconcile_orphaned_tasks(graph=app.state.graph)
    if task_recovery["scanned"]:
        logger.info("task startup reconciliation: %s", task_recovery)

    async def checkpoint_cache_loop():
        while True:
            try:
                removed = await checkpoint_service.cleanup_expired()
                if removed:
                    logger.info("checkpoint TTL 清理：删除 %d 个会话快照目录", removed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("checkpoint TTL 清理异常: %s", exc)
            await asyncio.sleep(3600)

    cleanup_task = asyncio.create_task(session_cache_loop(settings), name="session-cache-ttl")
    checkpoint_cleanup_task = asyncio.create_task(checkpoint_cache_loop(), name="checkpoint-cache-ttl")
    logger.info("lifespan ready: graph compiled, checkpointer up")
    yield
    cleanup_task.cancel()
    checkpoint_cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task
    with suppress(asyncio.CancelledError):
        await checkpoint_cleanup_task
    await cleanup_runtime(runtime)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(title="Agent Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next):
        trace_id = request.headers.get("X-Trace-ID") or uuid.uuid4().hex[:32]
        set_trace_id(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(status_code=http_status_for(exc.code), content=fail(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=fail(42200, "请求参数校验失败"))

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("unhandled error: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content=fail(ERR_INTERNAL, "服务器内部错误"))

    for router in (
        conversations.router,
        checkpoints.router,
        chat.router,
        tools.router,
        tasks.router,
        memory.router,
        kb.router,
        attachments.router,
        notifications.router,
        settings_router.router,
        system.router,
        skills.router,
        workspaces.router,
    ):
        app.include_router(router, prefix=settings.base_url)

    # 本地单机化：前端构建产物静态托管（单端口 8000；SPA 深链 fallback → index.html）
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    dist = Path(settings.frontend_dist)
    if dist.is_dir():

        class SPAStaticFiles(StaticFiles):
            """SPA fallback：非 /api 路径 404 → index.html（前端深链刷新可直达）。

            starlette 1.6：文件缺失时 get_response 抛 HTTPException(404)（非返回响应）。
            """

            async def get_response(self, path: str, scope):
                from starlette.exceptions import HTTPException

                try:
                    response = await super().get_response(path, scope)
                except HTTPException as exc:
                    if exc.status_code == 404 and not path.startswith("api"):
                        return await super().get_response("index.html", scope)
                    raise
                if response.status_code == 404 and not path.startswith("api"):
                    response = await super().get_response("index.html", scope)
                return response

        app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="frontend")

    return app


app = create_app()
