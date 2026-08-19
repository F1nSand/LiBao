"""共享运行时初始化（M6-3 拆 worker 抽取）。

backend（app/api/main.py lifespan）与独立 worker（app/worker.py）都需同一套「db + redis + registry 同步」，
此处收敛为 init_runtime/cleanup_runtime，避免两处重复。checkpointer/graph 因生命周期差异（backend 要
yield、worker 要常驻 loop）仍由调用方各自 async with 展开。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.storage.db import init_db, set_sessionmaker
from app.storage.redis import init_redis
from app.tools.builtin import register_builtin_tools


@dataclass
class Runtime:
    engine: Any
    sessionmaker: Any
    redis: Any


async def init_runtime(settings: Settings | None = None) -> Runtime:
    """内置工具注册 + db/redis 初始化 + 默认组织 registry 同步（+ 全量 MCP 行重建）。"""
    settings = settings or get_settings()
    register_builtin_tools()
    engine, sessionmaker = init_db(settings)
    set_sessionmaker(sessionmaker)
    redis = init_redis(settings)

    # DB tool_definition.enabled 为事实源 → 启动时同步 registry（F7 + I5，与 M6 前 main.py 同逻辑）。
    from app.services.tool import ToolService

    async with sessionmaker() as session:
        from sqlalchemy import select

        from app.storage.models.org import Org

        org = (
            await session.execute(select(Org).where(Org.name == "默认组织", Org.deleted_at.is_(None)))
        ).scalar_one_or_none()
        if org is not None:
            await ToolService().sync_registry_from_db(session, org.id)
            # M6 前：启用 provider → 覆盖 Settings（LLM 即用配置的 provider）
            from app.services.provider import ProviderService

            await ProviderService().sync_active_to_settings(session, org.id)
        await ToolService().sync_registry_from_db(session)  # 全量：MCP 行重建（不动已有 spec enabled）

    return Runtime(engine=engine, sessionmaker=sessionmaker, redis=redis)


async def cleanup_runtime(runtime: Runtime) -> None:
    """关闭 redis + dispose engine（与 M6 前 main.py 收尾同逻辑）。"""
    from app.storage.redis import close_redis

    await close_redis()
    await runtime.engine.dispose()
