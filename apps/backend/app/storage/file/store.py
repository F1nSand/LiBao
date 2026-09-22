"""文件存储核心（本地单机化）：FileStore 进程单例 + FileContext 请求上下文。

- `FileStore`：目录骨架 + 实体表注册（惰性）+ JSONL 分文件追加/读取 + KB BM25 索引挂载。
- `FileContext`：请求级上下文（替代 AsyncSession）。`commit()` 全量 flush 落盘（tmp+replace 原子），
  `rollback()` 全量重载；`add(row)` 按模型类自动注册（遗留 session.add 调用点兜底）。
- 桥函数：`set_store/get_store`。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.storage.file.rows import Row
from app.storage.file.tables import FileTable, _append_line
from app.storage.models.agent import AgentConfig, AgentVersion
from app.storage.models.attachment import Attachment
from app.storage.models.conversation import Conversation
from app.storage.models.kb import KbCollection
from app.storage.models.mcp_server import McpServer
from app.storage.models.memory import LongTermMemory
from app.storage.models.notification import Notification
from app.storage.models.provider import ProviderConfig
from app.storage.models.sandbox_preference import SandboxPreference
from app.storage.models.task import Task
from app.storage.models.tool_definition import ToolDefinition
from app.storage.models.workspace import Workspace

logger = logging.getLogger(__name__)

# 实体表规格：name → (相对路径, 模型类)。repository 首次访问时惰性注册。
TABLE_SPECS: dict[str, tuple[str, type]] = {
    "conversations": ("conversations.json", Conversation),
    "tasks": ("tasks.json", Task),
    "attachments": ("attachments.json", Attachment),
    "agents": ("agents.json", AgentConfig),
    "agent_versions": ("agent_versions.json", AgentVersion),
    "memory_cards": ("memory_cards.json", LongTermMemory),
    "notifications": ("notifications.json", Notification),
    "providers": ("providers.json", ProviderConfig),
    "mcp_servers": ("mcp_servers.json", McpServer),
    "tool_definitions": ("tool_definitions.json", ToolDefinition),
    "workspaces": ("workspaces.json", Workspace),
    "kb_collections": ("kb_collections.json", KbCollection),
    "sandbox_preferences": ("sandbox_preferences.json", SandboxPreference),
}


class FileStore:
    """进程单例：目录骨架 + 表注册 + JSONL 分文件 + KB BM25 索引。"""

    def __init__(self, settings: Any = None) -> None:
        settings = settings or get_settings()
        self.root = Path(settings.agent_data_dir)
        self.kb_root = Path(settings.kb_root)
        self.tables: dict[str, FileTable] = {}
        self._jsonl_locks: dict[str, asyncio.Lock] = {}
        self.bm25: Any = None  # KB BM25 索引（bootstrap 构建，kb repository 读写）
        self.kb_lance_store: Any = None  # KB Lance 存储惰性创建；测试可按数据目录重置连接缓存

    # ---- 初始化 ----

    async def init(self) -> None:
        """目录骨架 + 预加载全部已注册表（运行期 register 不再有未加载覆盖风险）。"""
        for rel in (
            "sessions",
            "checkpoints",
            "code-checkpoints",
            "task_events",
            "memory/default/trace/_tasks",
            "data",
        ):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.kb_root).mkdir(parents=True, exist_ok=True)
        for name in list(self.tables):
            await self.tables[name]._ensure_loaded()  # noqa: SLF001  预加载（内部方法）

    # ---- 表 ----

    def table(self, name: str) -> FileTable:
        if name not in self.tables:
            rel, model = TABLE_SPECS[name]
            self.tables[name] = FileTable(self.root, rel, model)
        return self.tables[name]

    def register_row(self, row: Row) -> None:
        """按模型类反查注册行到对应表（FileContext.add 对 Row 的兜底：测试/遗留调用点
        直接 session.add(AgentConfig(...)) 也能落盘；未注册模型（版本 JSONL 等）静默忽略）。"""
        for name, (_, model) in TABLE_SPECS.items():
            if isinstance(row, model):
                self.table(name).register(row)
                return

    # ---- JSONL 分文件（消息/轨迹/版本）----

    async def jsonl_append(self, rel_path: str, record: dict[str, Any]) -> None:
        path = self.root / rel_path
        lock = self._jsonl_locks.setdefault(rel_path, asyncio.Lock())
        async with lock:
            line = json.dumps(record, ensure_ascii=False)
            await asyncio.to_thread(_append_line, path, line)

    async def jsonl_list(self, rel_path: str) -> list[dict[str, Any]]:
        path = self.root / rel_path
        if not path.exists():
            return []
        lock = self._jsonl_locks.setdefault(rel_path, asyncio.Lock())
        async with lock:
            return await asyncio.to_thread(_read_jsonl, path)

    # ---- 上下文 ----

    @asynccontextmanager
    async def session(self) -> AsyncIterator[FileContext]:
        """请求级文件上下文。用法：`async with get_store().session() as db: ...`。"""
        yield FileContext(self)


class FileContext:
    """替代 AsyncSession 的请求级上下文（纯文件）。"""

    def __init__(self, store: FileStore) -> None:
        self.store = store

    def add(self, row: Any) -> None:
        """Row 按模型类自动注册到对应表（commit 时落盘）。"""
        if isinstance(row, Row):
            self.store.register_row(row)

    # ---- 兼容 API（历史调用点；文件行无需 flush/refresh）----

    async def flush(self) -> None:
        """no-op（文件行 id 在 __init__ 已生成，无需 flush 拿 id）。"""

    async def refresh(self, row: Any) -> None:
        """no-op（文件行内存即最新）。"""

    # ---- 提交 / 回滚 ----

    async def commit(self) -> None:
        """全部表全量序列化落盘（tmp+replace 原子）。"""
        # 请求并发时 repository 可能懒注册新表；快照遍历避免迭代期间字典变更。
        for table in list(self.store.tables.values()):
            await table.flush()

    async def rollback(self) -> None:
        """全部表从磁盘重载（丢弃内存未提交修改）。"""
        for table in list(self.store.tables.values()):
            await table.reload()

    async def __aenter__(self) -> FileContext:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 半行（崩溃残留）跳过
    return out


# ---- 全局桥 ----

_store: FileStore | None = None


def set_store(store: FileStore) -> None:
    global _store
    _store = store


def get_store() -> FileStore | None:
    return _store
