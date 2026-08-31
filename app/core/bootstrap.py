"""共享运行时初始化（本地单机化）：内置工具注册 + FileStore 初始化 + 首启种子 +
工具/Provider registry 文件同步 + KB BM25 索引构建。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.storage.file.store import FileStore, set_store
from app.tools.builtin import register_builtin_tools


@dataclass
class Runtime:
    store: FileStore


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

    # KB BM25 索引（启动构建：扫 kb/*/index.json）
    from app.storage.repositories.bm25 import BM25Index
    from app.storage.repositories.kb import KbRepository

    store.bm25 = BM25Index()
    store.bm25.rebuild(await KbRepository()._bm25_corpus())  # noqa: SLF001  全量语料（个人量级毫秒级）

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

    return Runtime(store=store)


async def cleanup_runtime(runtime: Runtime) -> None:
    """文件存储无连接需清理（保留对称入口）。"""
    return None
