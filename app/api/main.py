"""应用工厂（docs 01 §5.1）。create_app + lifespan + trace_id 中间件 + 统一异常 → 信封。

Windows 关键：psycopg async 需 SelectorEventLoop，而 Windows 默认 ProactorEventLoop 不兼容；
在模块顶层设置策略，使 uvicorn 创建事件循环时即用 Selector（langgraph AsyncPostgresSaver 依赖）。
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from contextlib import asynccontextmanager

import uvicorn.config as _uvicorn_config
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.envelope import fail
from app.api.routers import agents, auth, chat, conversations, system, tasks, tools
from app.core.config import get_settings
from app.core.errors import ERR_INTERNAL, AppError, http_status_for
from app.core.logging import set_trace_id, setup_logging
from app.orchestration.checkpointer import PostgresCheckpointer
from app.orchestration.graph import build_graph
from app.storage.db import init_db
from app.tools.builtin import register_builtin_tools

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def selector_loop_factory(use_subprocess: bool = False) -> type[asyncio.AbstractEventLoop]:
    """uvicorn loop 工厂：Windows 上强制 SelectorEventLoop（psycopg async 不兼容 Proactor）。"""
    return asyncio.SelectorEventLoop


if sys.platform == "win32":
    # uvicorn 用自身 loop 工厂（忽略事件循环策略）；覆盖 auto/asyncio 指向 selector，
    # 使 `uvicorn app.api.main:app` 无需附加参数即可运行（psycopg async 硬性要求）。
    _uvicorn_config.LOOP_FACTORIES["auto"] = "app.api.main:selector_loop_factory"
    _uvicorn_config.LOOP_FACTORIES["asyncio"] = "app.api.main:selector_loop_factory"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    register_builtin_tools()
    engine, sessionmaker = init_db(settings)
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    # checkpoint 表由 setup() 创建（须在 alembic upgrade head 之后，langgraph#2570 规避）
    async with PostgresCheckpointer(settings.sync_checkpoint_dsn) as saver:
        app.state.checkpointer = saver
        app.state.graph = build_graph(saver)
        logger.info("lifespan ready: graph compiled, checkpointer up")
        yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(title="Agent Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
        auth.router,
        conversations.router,
        agents.router,
        chat.router,
        tools.router,
        tasks.router,
        system.router,
    ):
        app.include_router(router, prefix=settings.base_url)

    return app


app = create_app()
