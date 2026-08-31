"""任务运行器（本地单机化）：进程内跑图（spawn_run）+ 可取消（route_cancel）。

Redis 与独立 worker 已删；任务提交/resume 直接 spawn_run（asyncio.create_task）注册进 _RUNNING，
POST /tasks/{id}/cancel 经 route_cancel 真正中断运行中的图。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from app.orchestration.task_run import recover_task_graph, resume_task_graph, run_task_graph

logger = logging.getLogger(__name__)

# in-flight 任务注册表（task_id → asyncio.Task），供 cancel 真正中断运行中的图。
_RUNNING: dict[str, asyncio.Task] = {}
_CANCEL_REQUESTED: set[str] = set()


def running_task(task_id: str) -> asyncio.Task | None:
    """取运行中任务的 asyncio.Task（无/已结束 → None）。"""
    return _RUNNING.get(task_id)


def task_guard(task_id: str) -> asyncio.Lock:
    """返回与 TaskService 状态迁移共用的任务级生命周期锁。"""
    # 延迟导入避免 task_worker → task_run → TaskService 的模块环。
    from app.services.task import _transition_lock

    return _transition_lock(task_id)


def register_running_task(task_id: str, task: asyncio.Task) -> None:
    """注册由 SSE 聊天流直接创建的 producer，纳入统一取消路由。"""
    key = str(task_id)
    _RUNNING[key] = task
    # HTTP cancel 可能先于 chat producer 注册；取消意图必须跨过这个窗口。
    if key in _CANCEL_REQUESTED and not task.done():
        task.cancel()


def unregister_running_task(task_id: str, task: asyncio.Task | None = None) -> None:
    """仅注销仍指向同一个 asyncio.Task 的条目，避免新一轮覆盖旧一轮。"""
    key = str(task_id)
    current = _RUNNING.get(key)
    if task is None or current is task:
        _RUNNING.pop(key, None)
        _CANCEL_REQUESTED.discard(key)


def clear_cancel_requested(task_id: str) -> None:
    """清理尚未注册 producer 的取消意图（入口已观察到 Task=cancelled）。"""
    _CANCEL_REQUESTED.discard(str(task_id))


def cancel_requested(task_id: str) -> bool:
    return str(task_id) in _CANCEL_REQUESTED


def spawn_run(
    *,
    graph: Any,
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
                    graph=graph, task_id=task_id,
                    approved=approved, trace_id=trace_id, model_override=model_override,
                )
            else:
                await run_task_graph(
                    graph=graph, task_id=task_id,
                    trace_id=trace_id, model_override=model_override,
                )
        finally:
            unregister_running_task(key, fut)

    fut = asyncio.create_task(_runner())
    register_running_task(key, fut)
    return fut


def spawn_recovery(*, graph: Any, task_id: uuid.UUID, trace_id: str, model_override: Any = None) -> asyncio.Task:
    """启动失败 checkpoint 恢复；与 confirmation resume 分开，避免误传 Command(resume)。"""
    key = str(task_id)

    async def _runner() -> None:
        try:
            await recover_task_graph(graph=graph, task_id=task_id, trace_id=trace_id, model_override=model_override)
        finally:
            unregister_running_task(key, fut)

    fut = asyncio.create_task(_runner())
    register_running_task(key, fut)
    return fut


async def route_cancel(task_id: str) -> None:
    """取消路由（进程内唯一路径）：本地 fut.cancel() 中断运行中的图。"""
    _CANCEL_REQUESTED.add(str(task_id))
    fut = running_task(task_id)
    if fut is not None and not fut.done():
        fut.cancel()
