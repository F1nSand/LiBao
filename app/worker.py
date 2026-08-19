"""独立任务 worker 入口（M6-3，docs 05 §2.1）：消费 Redis 队列跑 LangGraph 图，与 backend 进程分离。

运行：uv run python -m app.worker
与 backend 差异：不挂 FastAPI 路由，只做「共享初始化 + checkpointer/graph + cancel_listener + task_worker 循环」。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys

if sys.platform == "win32":
    # psycopg async（checkpointer）需 SelectorEventLoop；worker 不用 uvicorn，故不 patch LOOP_FACTORIES
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.core.bootstrap import cleanup_runtime, init_runtime
from app.core.config import get_settings
from app.core.instance import get_instance_id
from app.core.logging import setup_logging
from app.orchestration.checkpointer import PostgresCheckpointer
from app.orchestration.graph import build_graph
from app.orchestration.task_worker import cancel_listener, task_worker

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    runtime = await init_runtime(settings)
    instance_id = get_instance_id()
    async with PostgresCheckpointer(settings.sync_checkpoint_dsn) as saver:
        graph = build_graph(saver)
        stop = asyncio.Event()

        # SIGINT/SIGTERM → 优雅退出（Windows 上 add_signal_handler 可能不支持，忽略即可，靠进程终止兜底）
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop.set)

        cancel_t = asyncio.create_task(cancel_listener(instance_id))
        worker_t = asyncio.create_task(task_worker(graph, runtime.sessionmaker, stop))
        logger.info("worker ready: instance=%s, graph compiled, checkpointer up", instance_id)
        await stop.wait()

        cancel_t.cancel()
        worker_t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cancel_t
            await worker_t
    await cleanup_runtime(runtime)


if __name__ == "__main__":
    asyncio.run(main())
