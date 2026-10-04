"""共享运行时初始化（本地单机化）：内置工具注册 + FileStore 初始化 + 首启种子 +
工具/Provider registry 文件同步 + legacy KB BM25 回退初始化。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings, get_settings
from app.services.kb_migration import KbV2Migrator, MigrationReport
from app.storage.file.store import FileStore, set_store
from app.tools.builtin import register_builtin_tools

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    store: FileStore
    kb_index_mode: Literal["v2", "legacy_degraded"]
    kb_migration: MigrationReport


async def init_runtime(settings: Settings | None = None) -> Runtime:
    """内置工具注册 + FileStore 初始化 + 种子 + 工具/Provider 同步 + BM25 构建。"""
    settings = settings or get_settings()
    register_builtin_tools()

    # 默认部署只使用 ~/.LiBao；测试传自定义 settings 时不写用户配置。
    if settings is get_settings():
        from app.core.settings_upgrade import initialize_user_settings, normalize_legacy_model_prefix

        initialize_user_settings(settings)
        normalize_legacy_model_prefix(settings)  # 去 liteLLM 模型名前缀（纯 OpenAI 协议迁移）

    store = FileStore(settings)
    await store.init()
    set_store(store)

    kb_index_mode, kb_migration = await initialize_kb_indexing(
        store, force_legacy=settings.kb_force_legacy_mode
    )

    # 本地单机化：tool_definitions.json enabled 为事实源 → registry 同步 + MCP 行重建
    from app.seed import ensure_seed_tools, seed_if_first_run
    from app.services.provider import ProviderService
    from app.services.sandbox import SandboxService
    from app.services.tool import ToolService

    await seed_if_first_run(store)  # 首启落种子（幂等）
    await ensure_seed_tools(store)  # 升级合并：老数据环境补新工具（P4 记忆工具）+ agent.tools 扩展
    await ToolService().sync_registry_from_file()
    await ProviderService().sync_active_to_settings()
    async with store.session() as db:
        await SandboxService().sync_runtime(db)

    return Runtime(store=store, kb_index_mode=kb_index_mode, kb_migration=kb_migration)


async def initialize_kb_indexing(
    store: FileStore,
    *,
    force_legacy: bool = False,
) -> tuple[Literal["v2", "legacy_degraded"], MigrationReport]:
    """Migrate before serving; retain an explicit switch for operational rollback."""
    from app.storage.repositories.bm25 import BM25Index
    from app.storage.repositories.kb import KbRepository

    store.bm25 = BM25Index()
    store.kb_index_mode = "legacy_degraded"
    store.kb_force_legacy_mode = force_legacy
    repo = KbRepository()
    if force_legacy:
        report = MigrationReport(0, 0, 0, 0, 0, False)
        logger.warning("KB running in forced legacy mode")
    else:
        try:
            report = await KbV2Migrator(repo=repo).migrate_all()
        except Exception as exc:  # noqa: BLE001  preserve old retrieval and retry migration next startup
            logger.warning("KB migration failed error_type=%s", type(exc).__name__)
            report = MigrationReport(0, 0, 0, 0, 1, False)

    try:
        await repo.lance.ensure_ready()
        fts_ready = True
    except Exception as exc:  # noqa: BLE001  expose a degraded mode rather than failing app startup
        logger.warning("KB FTS initialization failed error_type=%s", type(exc).__name__)
        fts_ready = False

    if report.complete and fts_ready and not force_legacy:
        store.kb_index_mode = "v2"
    else:
        await rebuild_legacy_bm25_fallback(store)
    store.kb_migration = report
    return store.kb_index_mode, report


async def rebuild_legacy_bm25_fallback(store: FileStore) -> None:
    """Rebuild once at startup when migration is incomplete, including active v2 chunks."""
    from app.storage.repositories.kb import KbRepository

    store.bm25.rebuild(await KbRepository()._bm25_corpus())  # noqa: SLF001  degraded-mode compatibility


async def rebuild_legacy_bm25_if_needed(store: FileStore) -> bool:
    """Build the temporary BM25 fallback only while indexed v1 documents remain."""
    from app.storage.repositories.kb import KbRepository

    repo = KbRepository()
    if not await repo.has_legacy_active_documents():
        return False
    store.bm25.rebuild(await repo._bm25_corpus())  # noqa: SLF001  legacy compatibility fallback
    return True


async def cleanup_runtime(runtime: Runtime) -> None:
    """文件存储无连接需清理（保留对称入口）。"""
    return None
