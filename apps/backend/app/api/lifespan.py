"""Application startup and shutdown orchestration."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.checkpoints.runtime import get_checkpoint_service
from app.core.bootstrap import cleanup_runtime, init_runtime
from app.core.config import get_settings
from app.core.session_cache import session_cache_loop
from app.orchestration.checkpointer import build_checkpointer
from app.orchestration.graph import build_graph
from app.services.kb_recovery import kb_maintenance_loop, reconcile_kb_index
from app.services.task_recovery import reconcile_orphaned_tasks

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the local runtime and stop background maintenance cleanly."""

    settings = get_settings()
    runtime = await init_runtime(settings)
    app.state.store = runtime.store
    app.state.kb_index_mode = runtime.kb_index_mode
    app.state.kb_migration = runtime.kb_migration
    # 本地单机化：JsonFileSaver（.agent/checkpoints/），resume 语义与 PostgresSaver 等价
    saver = build_checkpointer(settings)
    app.state.checkpointer = saver
    app.state.graph = build_graph(saver)

    checkpoint_service = get_checkpoint_service(settings.agent_data_dir, settings.checkpoint_retention_days)
    recovered = await checkpoint_service.recover_open_checkpoints()
    if recovered:
        logger.info("checkpoint crash recovery: marked %d open manifests interrupted", recovered)
    recovered_operations = await checkpoint_service.recover_incomplete_operations()
    if recovered_operations:
        logger.info("rollback operation recovery: marked %d incomplete journals failed_partial", recovered_operations)
    task_recovery = await reconcile_orphaned_tasks(graph=app.state.graph)
    if task_recovery["scanned"]:
        logger.info("task startup reconciliation: %s", task_recovery)
    if settings.kb_recovery_enabled:
        kb_recovery = await reconcile_kb_index()
        if kb_recovery.repaired or kb_recovery.errors or kb_recovery.repair_required:
            logger.info("KB startup reconciliation: %s", kb_recovery)

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
    kb_cleanup_task = (
        asyncio.create_task(kb_maintenance_loop(settings), name="kb-index-maintenance")
        if settings.kb_recovery_enabled
        else None
    )
    logger.info("lifespan ready: graph compiled, checkpointer up")
    yield
    cleanup_task.cancel()
    checkpoint_cleanup_task.cancel()
    if kb_cleanup_task is not None:
        kb_cleanup_task.cancel()
    with suppress(asyncio.CancelledError):
        await cleanup_task
    with suppress(asyncio.CancelledError):
        await checkpoint_cleanup_task
    if kb_cleanup_task is not None:
        with suppress(asyncio.CancelledError):
            await kb_cleanup_task
    await cleanup_runtime(runtime)
