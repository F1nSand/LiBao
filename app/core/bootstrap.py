"""共享运行时初始化（本地单机化双轨期：文件存储 + SQL 兜底，P4 全文件化后简化）。

backend（app/api/main.py lifespan）与测试共用：内置工具注册 + FileStore 初始化 +
SQL 引擎（未文件化实体兜底）+ 工具/Provider registry 文件同步。
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
    """内置工具注册 + FileStore 初始化 + SQL 引擎（双轨）+ 工具/Provider 文件同步。"""
    settings = settings or get_settings()
    register_builtin_tools()
    engine, sessionmaker = init_db(settings)
    set_sessionmaker(sessionmaker)

    store = FileStore(settings)
    store.sql_sessionmaker = sessionmaker  # 双轨：未文件化 repository 的 SQL 兜底
    await store.init()
    set_store(store)

    # KB BM25 索引（启动构建：扫 kb/*/index.json）
    from app.storage.repositories.bm25 import BM25Index
    from app.storage.repositories.kb import KbRepository

    store.bm25 = BM25Index()
    store.bm25.rebuild(await KbRepository()._bm25_corpus())  # noqa: SLF001  全量语料（个人量级毫秒级）

    # 本地单机化：tool_definitions.json enabled 为事实源 → registry 同步 + MCP 行重建
    from app.seed import seed_if_first_run
    from app.services.provider import ProviderService
    from app.services.tool import ToolService

    await seed_if_first_run(store)  # 首启落种子（幂等）
    await ToolService().sync_registry_from_file()
    await ProviderService().sync_active_to_settings()

    return Runtime(engine=engine, sessionmaker=sessionmaker, store=store)


async def cleanup_runtime(runtime: Runtime) -> None:
    """dispose engine（文件存储无连接需清理）。"""
    await runtime.engine.dispose()
