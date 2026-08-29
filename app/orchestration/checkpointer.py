"""LangGraph checkpointer 封装（本地单机化）：JsonFileSaver（BaseCheckpointSaver 子类）。

断点落 `.agent/checkpoints/<thread_key>.json`（thread_key = thread_id，subagent 场景拼 checkpoint_ns）。
文件结构：{schema_version, next_version, checkpoints: {<checkpoint_id>: {checkpoint, metadata, writes}}}。
序列化走 langchain_core.load（LangChain 消息安全）；写盘 tmp+os.replace 原子；线程锁串行化。

async 变体（aput/aput_writes/aget_tuple/alist）用 asyncio.to_thread 包装，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import tempfile
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
)

from app.orchestration.checkpoint_codec import JsonCheckpointCodec

SCHEMA_VERSION = 2


def _checkpoint_before_failed_input(records: dict[str, Any], latest_id: str, codec: JsonCheckpointCodec) -> str | None:
    latest = records[latest_id]
    has_error = any(
        pair[0] == "__error__"
        for task_writes in (latest.get("writes") or {}).values()
        for pair in task_writes
    )
    if not has_error:
        return latest_id
    ids = sorted(records)
    for index in range(ids.index(latest_id), -1, -1):
        metadata = codec.loads(records[ids[index]]["metadata"], channel="metadata")
        if metadata.get("source") == "input":
            return ids[index - 1] if index > 0 else None
    return latest_id


def _latest_failed_checkpoint_id(records: dict[str, Any]) -> str | None:
    """返回挂有 LangGraph ``__error__`` pending write 的最新节点输入 checkpoint。"""

    for checkpoint_id in sorted(records, reverse=True):
        writes = records[checkpoint_id].get("writes") or {}
        if any(channel == "__error__" for task_writes in writes.values() for channel, _ in task_writes):
            return checkpoint_id
    return None


def _thread_key(config: dict[str, Any]) -> str:
    """thread_key = thread_id（subagent 场景拼 checkpoint_ns 的 sha1 短前缀，防同目录碰撞）。"""
    cfg = config.get("configurable", config)
    thread_id = str(cfg.get("thread_id", ""))
    ns = cfg.get("checkpoint_ns")
    if ns:
        suffix = hashlib.sha1(str(ns).encode()).hexdigest()[:12]
        thread_id = f"{thread_id}__{suffix}"
    return thread_id or "default"


class JsonFileSaver(BaseCheckpointSaver):
    """文件断点 saver：按 thread_key 单文件存全量 checkpoint 记录。"""

    def __init__(self, root: Path, *, serde: SerializerProtocol | None = None) -> None:
        super().__init__(serde=serde)
        self.codec = JsonCheckpointCodec(self.serde)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}

    # ---- 文件读写（线程安全）----

    def _lock(self, key: str) -> threading.Lock:
        return self._locks.setdefault(key, threading.Lock())

    def _path(self, config: dict[str, Any]) -> Path:
        return self.root / f"{_thread_key(config)}.json"

    def _load(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"schema_version": SCHEMA_VERSION, "checkpoints": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"schema_version": SCHEMA_VERSION, "checkpoints": {}}

    def _save(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            with _suppress_oserror():
                os.unlink(tmp)
            raise

    # ---- BaseCheckpointSaver 同步核心 ----

    def get_next_version(self, current: Any, channel: Any) -> str:
        """版本格式与 MemorySaver 对齐：`{n:032}.{rand:016}`（langgraph 续跑时解析
        int(version.split('.')[0]) 比较 channel 更新——uuid4 字符串会解析失败致续跑短路）。"""
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(str(current).split(".")[0])
        return f"{current_v + 1:032}.{random.random():016}"

    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> str:
        path = self._path(config)
        with self._lock(str(path)):
            data = self._load(path)
            checkpoint_id = str(checkpoint["id"])
            # LangChain 消息/状态对象经 lc_dumps 安全序列化
            data["checkpoints"][checkpoint_id] = {
                "checkpoint": self.codec.dumps(checkpoint),
                "metadata": self.codec.dumps(metadata),
                "writes": {},
            }
            self._save(path, data)
        return checkpoint_id

    def put_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        path = self._path(config)
        with self._lock(str(path)):
            data = self._load(path)
            cid = (config.get("configurable", config) or {}).get("checkpoint_id")
            if cid is None:
                return  # 无 checkpoint_id 无法挂 writes（正常流程必有）
            cid = str(cid)
            rec = data["checkpoints"].get(cid)
            if rec is None:
                return
            rec["writes"][task_id] = [
                [
                    ch,
                    (
                        self.codec.dumps({"error_type": type(val).__name__})
                        if ch == "__error__" and isinstance(val, BaseException)
                        else self.codec.dumps(val)
                    ),
                ]
                for ch, val in writes
            ]
            self._save(path, data)

    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        path = self._path(config)
        with self._lock(str(path)):
            data = self._load(path)
            cfg = config.get("configurable", config)
            cid = cfg.get("checkpoint_id")
            recs = data["checkpoints"]
            if cid is not None and str(cid) in recs:
                record = recs[str(cid)]
            elif recs:
                latest_id = max(recs.keys())  # checkpoint_id 可比较 → 最新
                checkpoint_id = _checkpoint_before_failed_input(recs, latest_id, self.codec)
                if checkpoint_id is None:
                    return None
                record = recs[checkpoint_id]
            else:
                return None
            checkpoint: Checkpoint = self.codec.loads(record["checkpoint"], channel="checkpoint")
            metadata: CheckpointMetadata = self.codec.loads(record["metadata"], channel="metadata")
            parent_id = checkpoint.get("parent_checkpoint_id")
            parent_config = None
            if parent_id:
                parent_config = {"configurable": {**cfg, "checkpoint_id": parent_id}}
            pending_writes: list[tuple[str, str, Any]] = []
            for tid, chans in (record.get("writes") or {}).items():
                for ch, val in chans:
                    pending_writes.append((tid, ch, self.codec.loads(val, channel=ch)))
            return CheckpointTuple(
                config={"configurable": {**cfg, "checkpoint_id": checkpoint["id"]}},
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
                pending_writes=pending_writes,
            )

    def get_failed_config(self, config: dict[str, Any]) -> dict[str, Any] | None:
        """显式读取失败节点 checkpoint，避免普通读取为新用户消息回滚失败输入。"""

        path = self._path(config)
        with self._lock(str(path)):
            data = self._load(path)
            checkpoint_id = _latest_failed_checkpoint_id(data.get("checkpoints") or {})
            if checkpoint_id is None:
                return None
            cfg = config.get("configurable", config) or {}
            return {"configurable": {**cfg, "checkpoint_id": checkpoint_id}}

    def list(
        self,
        config: dict[str, Any],
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        path = self._path(config)
        with self._lock(str(path)):
            data = self._load(path)
            ids = sorted(data["checkpoints"].keys())
            if before is not None:
                bcid = (before.get("configurable", before) or {}).get("checkpoint_id")
                if bcid is not None:
                    ids = [i for i in ids if i < str(bcid)]
            ids.reverse()  # 新→旧
            if limit is not None:
                ids = ids[:limit]
            tuples = []
            for i in ids:
                rec = data["checkpoints"][i]
                tuples.append(
                    CheckpointTuple(
                        config={"configurable": {**config.get("configurable", {}), "checkpoint_id": i}},
                        checkpoint=self.codec.loads(rec["checkpoint"], channel="checkpoint"),
                        metadata=self.codec.loads(rec["metadata"], channel="metadata"),
                        parent_config=None,
                        pending_writes=[],
                    )
                )
        return iter(tuples)

    def delete_thread(self, thread_id: str) -> None:
        """删除整个线程的断点文件（工作区硬删/会话清理时调用）。"""
        path = self.root / f"{thread_id}.json"
        with _suppress_oserror():
            path.unlink()

    # ---- async 变体（to_thread 包装，避免阻塞事件循环）----

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> str:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self, config: dict[str, Any], writes: Sequence[tuple[str, Any]], task_id: str, task_path: str = ""
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        return await asyncio.to_thread(self.get_tuple, config)

    async def aget_failed_config(self, config: dict[str, Any]) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.get_failed_config, config)

    async def alist(
        self,
        config: dict[str, Any],
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[CheckpointTuple]:
        return await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )


def build_checkpointer(settings: Any) -> JsonFileSaver:
    """按配置构建 JsonFileSaver（根目录 .agent/checkpoints）。"""

    root = Path(settings.agent_data_dir) / "checkpoints"
    return JsonFileSaver(root)


import contextlib  # noqa: E402


@contextlib.contextmanager
def _suppress_oserror():
    try:
        yield
    except OSError:
        pass
