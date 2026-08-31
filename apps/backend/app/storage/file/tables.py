"""文件存储表设施（本地单机化）。

- `FileTable`：可变实体 → 单文件 JSON `{version, items: {id: row_dict}}`，内存为单一事实源，
  `flush()` 全量序列化 + tmp/rename 原子落盘（个人量级每表数十行，全量写成本可忽略，
  且天然规避脏行追踪漏写——commit 时写出的总是最新内存状态）。
- `JsonlTable`：append-only JSONL（消息/轨迹/版本），追加即落盘，读取半行跳过（崩溃安全）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from app.storage.file.rows import Row

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Row)


class FileTable[T]:
    """单文件 JSON 实体表（可变实体）。"""

    def __init__(self, root: Path, rel_path: str, model_cls: type[T]) -> None:
        self.root = root
        self.path = root / rel_path
        self.model = model_cls
        self._items: dict[str, T] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    # ---- 加载 ----

    def _load_now(self) -> None:
        """同步加载（register/delete_row 前置）：未加载表先读磁盘再写内存，
        否则后续 _ensure_loaded 整体覆盖会丢掉新写入的未落盘行
        （启动后首请求窗口的会话行丢失根因，2026-08-23 定位）。"""
        if self._loaded:
            return
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                items = data.get("items", {})
                self._items = {k: self.model.from_dict(v) for k, v in items.items()}
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                # 半写/损坏 → 空表启动（原子替换后不应出现；兜底防启动即挂）
                logger.warning("FileTable %s 读取失败，空表启动: %s", self.path, exc)
                self._items = {}
        self._loaded = True

    async def _ensure_loaded(self) -> None:
        self._load_now()

    # ---- 读取（内存操作，单进程事件循环内原子）----

    async def get(self, row_id: Any) -> T | None:
        await self._ensure_loaded()
        return self._items.get(str(row_id))

    async def list(
        self,
        *,
        filter_fn: Callable[[T], bool] | None = None,
        sort_key: Callable[[T], Any] | None = None,
        desc: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[T]:
        """内存过滤/排序/分页（等价原 SQL 语义；个人量级全量遍历可接受）。"""
        await self._ensure_loaded()
        rows = list(self._items.values())
        if filter_fn is not None:
            rows = [r for r in rows if filter_fn(r)]
        if sort_key is not None:
            rows.sort(key=sort_key, reverse=desc)
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows

    async def count(self, *, filter_fn: Callable[[T], bool] | None = None) -> int:
        await self._ensure_loaded()
        if filter_fn is None:
            return len(self._items)
        return sum(1 for r in self._items.values() if filter_fn(r))

    # ---- 写入（内存标脏，commit 时 flush 落盘）----

    def register(self, row: T) -> None:
        """新增行：入内存 + 标脏（供 repository create 调用）。"""
        self._load_now()  # 未加载表先读磁盘（防 _ensure_loaded 整体覆盖丢新行）
        self._items[str(row.id)] = row
        row.mark_clean()  # 新行视为已持久化基线（服务层后续赋值才标脏）

    def delete_row(self, row: T) -> None:
        """硬删行：从内存移除（供 repository 级联硬删调用）。"""
        self._load_now()  # 同上：未加载表先读磁盘（否则删除无效且 flush 写回旧行）
        self._items.pop(str(row.id), None)

    async def flush(self) -> None:
        """全量序列化落盘（tmp + os.replace 原子）。"""
        async with self._lock:
            await self._ensure_loaded()
            data = {"version": 1, "items": {k: v.to_dict() for k, v in self._items.items()}}
            payload = json.dumps(data, ensure_ascii=False, indent=1)
            await asyncio.to_thread(_atomic_write, self.path, payload)

    async def reload(self) -> None:
        """回滚：丢弃内存修改，从磁盘重载。"""
        async with self._lock:
            self._loaded = False
            self._items = {}
            await self._ensure_loaded()


class JsonlTable:
    """append-only JSONL 表（消息/轨迹/版本）：追加即落盘，全量载入内存供查询。

    单个文件场景（如记忆版本）；会话消息按 key 分文件的场景走 FileStore.jsonl_append。
    """

    def __init__(self, root: Path, rel_path: str) -> None:
        self.root = root
        self.path = root / rel_path
        self._records: list[dict[str, Any]] = []
        self._loaded = False
        self._lock = asyncio.Lock()

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        records: list[dict[str, Any]] = []
        if self.path.exists():
            async with self._lock:
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # 半行（崩溃残留）跳过
        self._records = records
        self._loaded = True

    async def append(self, record: dict[str, Any]) -> None:
        async with self._lock:
            await self._ensure_loaded()
            line = json.dumps(record, ensure_ascii=False)
            await asyncio.to_thread(_append_line, self.path, line)
            self._records.append(record)

    async def all(self) -> list[dict[str, Any]]:
        await self._ensure_loaded()
        return list(self._records)

    async def count(self) -> int:
        await self._ensure_loaded()
        return len(self._records)


def _atomic_write(path: Path, payload: str) -> None:
    """tmp 文件写入 + os.replace 原子替换（Windows 兼容）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    except BaseException:
        with _suppress_oserror():
            os.unlink(tmp)
        raise


def _append_line(path: Path, line: str) -> None:
    """JSONL 追加（'a' 模式原子到行；Windows 编码 utf-8）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


import contextlib  # noqa: E402  局部导入避免顶部顺序噪声


@contextlib.contextmanager
def _suppress_oserror():
    try:
        yield
    except OSError:
        pass
