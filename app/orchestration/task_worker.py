"""任务 worker（M4）：BRPOP 消费任务队列 → 分派到 run_task_graph / resume_task_graph。

单实例 MVP：worker 为 lifespan 常驻协程（SelectorEventLoop 下 async BRPOP 不阻塞）。
BRPOP timeout=1 让 worker 周期性观察 stop_event，优雅退出（先 stop 再 cancel 再 close redis）。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from app.core.logging import set_trace_id
from app.orchestration.task_run import resume_task_graph, run_task_graph
from app.storage.redis import brpop_task

logger = logging.getLogger(__name__)


async def process_one(graph: Any, sessionmaker: Any) -> bool:
    """brpop 一个任务并分派；无任务返回 False。trace_id 经 Redis 传输后必须恢复（run_log 断裂）。"""
    payload = await brpop_task()
    if payload is None:
        return False
    trace_id = payload.get("trace_id") or ""
    set_trace_id(trace_id)
    try:
        task_id = uuid.UUID(payload["task_id"])
        if payload.get("kind") == "resume":
            await resume_task_graph(
                graph=graph, sessionmaker=sessionmaker, task_id=task_id, approved=bool(payload.get("approved")),
                trace_id=trace_id,
            )
        else:
            await run_task_graph(graph=graph, sessionmaker=sessionmaker, task_id=task_id, trace_id=trace_id)
    except Exception as exc:  # noqa: BLE001  单任务分派失败不退出 worker
        logger.warning("task worker dispatch failed: %s", exc)
    return True


async def task_worker(graph: Any, sessionmaker: Any, stop: asyncio.Event) -> None:
    """常驻消费循环；每轮 BRPOP 超时后检查 stop_event 优雅退出。"""
    while not stop.is_set():
        try:
            await process_one(graph, sessionmaker)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  redis 抖动不退出
            logger.warning("task worker loop error: %s", exc)
            await asyncio.sleep(0.5)
