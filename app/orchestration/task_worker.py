"""任务运行器（本地单机化）：进程内跑图（spawn_run）+ 可取消（route_cancel）。

Redis 与独立 worker 已删；任务提交/resume 直接 spawn_run（asyncio.create_task）注册进 _RUNNING，
POST /tasks/{id}/cancel 经 route_cancel 真正中断运行中的图。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from app.orchestration.task_run import resume_task_graph, run_task_graph

logger = logging.getLogger(__name__)

# in-flight 任务注册表（task_id → asyncio.Task），供 cancel 真正中断运行中的图。
_RUNNING: dict[str, asyncio.Task] = {}


def running_task(task_id: str) -> asyncio.Task | None:
    """取运行中任务的 asyncio.Task（无/已结束 → None）。"""
    return _RUNNING.get(task_id)


def spawn_run(
    *,
    graph: Any,
    sessionmaker: Any,
    task_id: uuid.UUID,
    trace_id: str,
    approved: bool | None = None,
    model_override: Any = None,
) -> asyncio.Task:
    """以独立 asyncio.Task 跑 run_task_graph / resume_task_graph，并注册进 _RUNNING。

    - approved is None → run_task_graph（提交）；approved 是 bool → resume_task_graph（resume 双轨）。
    - 结束（含被取消）自动注销，防止注册表泄漏。
    """
    key = str(task_id)

    async def _runner() -> None:
        try:
            if approved is not None:
                await resume_task_graph(
                    graph=graph, sessionmaker=sessionmaker, task_id=task_id,
                    approved=approved, trace_id=trace_id, model_override=model_override,
                )
            else:
                await run_task_graph(
                    graph=graph, sessionmaker=sessionmaker, task_id=task_id,
                    trace_id=trace_id, model_override=model_override,
                )
        finally:
            _RUNNING.pop(key, None)

    fut = asyncio.create_task(_runner())
    _RUNNING[key] = fut
    return fut


async def route_cancel(task_id: str) -> None:
    """取消路由（进程内唯一路径）：本地 fut.cancel() 中断运行中的图。"""
    fut = running_task(task_id)
    if fut is not None and not fut.done():
        fut.cancel()
