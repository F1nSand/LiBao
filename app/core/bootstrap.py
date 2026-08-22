"""共享运行时初始化（本地单机化双轨期：文件存储 + SQL 兜底，P4 全文件化后简化）。

backend（app/api/main.py lifespan）与测试共用：内置工具注册 + FileStore 初始化 +
SQL 引擎（未文件化实体兜底）+ registry 同步。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.storage.db import init_db, set_sessionmaker
from app.storage.file.store import FileStore, set_store
from app.tools.builtin import register_builtin_tools


@dataclass
class Runtime:
    engine: Any
    sessionmaker: Any
    store: FileStore


async def init_runtime(settings: Settings | None = None) -> Runtime:
    """内置工具注册 + FileStore 初始化 + SQL 引擎（双轨）+ 默认组织 registry 同步。"""
    settings = settings or get_settings()
    register_builtin_tools()
    engine, sessionmaker = init_db(settings)
    set_sessionmaker(sessionmaker)

    store = FileStore(settings)
    store.sql_sessionmaker = sessionmaker  # 双轨：未文件化 repository 的 SQL 兜底
    await store.init()
    set_store(store)

    # DB tool_definition.enabled 为事实源 → 启动时同步 registry（F7 + I5，P2 改读文件）
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

    return Runtime(engine=engine, sessionmaker=sessionmaker, store=store)


async def cleanup_runtime(runtime: Runtime) -> None:
    """dispose engine（文件存储无连接需清理）。"""
    await runtime.engine.dispose()
