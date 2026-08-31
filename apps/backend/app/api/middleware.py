"""HTTP middleware and API error handlers."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.envelope import fail
from app.core.errors import ERR_INTERNAL, AppError, http_status_for
from app.core.logging import set_trace_id

logger = logging.getLogger(__name__)


def register_middleware(app: FastAPI) -> None:
    """Install transport-level tracing and the stable error envelope."""

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
