"""后台任务工具（Gate3 Simplify：spawn + 异常观测收敛，收敛 kb/attachment 两处重复）。"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


def log_task_failure(task: asyncio.Task) -> None:
    """后台任务异常观测（C5）：create_task 丢弃引用，异常会静默——done_callback 兜底记录。"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("后台任务失败: %s", exc)


def spawn_background(coro_fn: Callable[[Any, uuid.UUID], Awaitable[None]], arg: uuid.UUID) -> None:
    """经 sessionmaker 桥触发后台链（桥未设时静默）；done_callback 观测异常。"""
    from app.storage.db import get_sessionmaker

    sessionmaker = get_sessionmaker()
    if sessionmaker is not None:
        t = asyncio.create_task(coro_fn(sessionmaker, arg))
        t.add_done_callback(log_task_failure)
