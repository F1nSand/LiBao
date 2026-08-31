"""结构化日志 + trace_id 全链路（《02》后端设计 §2 core/logging.py，《02》架构总览 原则）。

trace_id 存于 ContextVar，随请求贯穿 API→编排→工具→LLM；
ASGI 中间件在 api/main.py 中设置。JSON 日志为 M5 观测性增强，M1 用 key=value 行即可。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="")


def set_trace_id(value: str) -> None:
    TRACE_ID.set(value)


def get_trace_id() -> str:
    return TRACE_ID.get()


class _TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True


def setup_logging(level: str = "INFO") -> None:
    """幂等配置根 logger（一次调用即可，全部模块共用）。"""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in root.handlers:
        if getattr(handler, "_traceid_handler", False):
            return
    handler = logging.StreamHandler()
    handler._traceid_handler = True  # type: ignore[attr-defined]
    handler.addFilter(_TraceIdFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(trace_id)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
