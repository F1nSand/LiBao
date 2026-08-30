"""会话隔离的 checkpoint manifest/blob 存储。

写入采用 ``tmp + os.replace``，并以会话粒度 asyncio.Lock 串行化 manifest/index 更新。
blob 是不可变内容寻址文件；manifest 的 mutation 记录是写前 WAL，便于进程在工具写入
中途退出后继续安全判断。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.checkpoints.models import (
    CheckpointIndex,
    CodeCheckpoint,
    FileMutationRecord,
    FileVersionRef,
    RollbackOperation,
)


class CheckpointStoreError(RuntimeError):
    """快照无法安全持久化或读取。"""


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_bytes(path, json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"))


def _content_kind(content: bytes) -> str:
    if b"\x00" in content:
        return "binary"
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    return "text"


class CodeCheckpointStore:
    def __init__(self, data_root: str | Path) -> None:
        self.data_root = Path(data_root)
        self.root = self.data_root / "code-checkpoints"
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    def session_dir(self, conversation_id: uuid.UUID | str) -> Path:
        return self.root / str(conversation_id)

    def _lock(self, conversation_id: uuid.UUID | str) -> asyncio.Lock:
        return self._locks.setdefault(str(conversation_id), asyncio.Lock())

    def _manifest_path(self, conversation_id: uuid.UUID | str, checkpoint_id: uuid.UUID | str) -> Path:
        return self.session_dir(conversation_id) / "manifests" / f"{checkpoint_id}.json"

    def _index_path(self, conversation_id: uuid.UUID | str) -> Path:
        return self.session_dir(conversation_id) / "index.json"

    def _operation_path(self, conversation_id: uuid.UUID | str, operation_id: uuid.UUID | str) -> Path:
        return self.session_dir(conversation_id) / "operations" / f"{operation_id}.json"

    def _blob_path(self, conversation_id: uuid.UUID | str, sha256: str) -> Path:
        return self.session_dir(conversation_id) / "blobs" / "sha256" / sha256[:2] / sha256

    async def _read_index_unlocked(self, conversation_id: uuid.UUID | str) -> CheckpointIndex:
        cid = uuid.UUID(str(conversation_id))
        path = self._index_path(cid)
        if not path.exists():
            return CheckpointIndex(conversation_id=cid)
        try:
            return CheckpointIndex.from_dict(json.loads(path.read_text(encoding="utf-8")), cid)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CheckpointStoreError("checkpoint index 无法安全读取") from exc

    async def _write_index_unlocked(self, index: CheckpointIndex) -> None:
        index.last_active_at = datetime.now(UTC)
        _atomic_write_json(self._index_path(index.conversation_id), index.to_dict())

    async def create_checkpoint(self, checkpoint: CodeCheckpoint) -> CodeCheckpoint:
        async with self._lock(checkpoint.conversation_id):
            path = self._manifest_path(checkpoint.conversation_id, checkpoint.id)
            if path.exists():
                try:
                    existing = CodeCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise CheckpointStoreError("checkpoint manifest 已损坏") from exc
                if existing is None:
                    raise CheckpointStoreError("checkpoint manifest 已损坏")
                return existing
            _atomic_write_json(path, checkpoint.to_dict())
            index = await self._read_index_unlocked(checkpoint.conversation_id)
            if checkpoint.id not in index.checkpoint_ids:
                index.checkpoint_ids.append(checkpoint.id)
            await self._write_index_unlocked(index)
            return checkpoint

    async def read_checkpoint(
        self, conversation_id: uuid.UUID | str, checkpoint_id: uuid.UUID | str
    ) -> CodeCheckpoint | None:
        path = self._manifest_path(conversation_id, checkpoint_id)
        if not path.exists():
            return None
        async with self._lock(conversation_id):
            try:
                return CodeCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise CheckpointStoreError("checkpoint manifest 无法安全读取") from exc

    async def create_operation(self, operation: RollbackOperation) -> RollbackOperation:
        async with self._lock(operation.conversation_id):
            path = self._operation_path(operation.conversation_id, operation.id)
            if path.exists():
                try:
                    return RollbackOperation.from_dict(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise CheckpointStoreError("rollback operation 已损坏") from exc
            _atomic_write_json(path, operation.to_dict())
            index = await self._read_index_unlocked(operation.conversation_id)
            if operation.id not in index.operation_ids:
                index.operation_ids.append(operation.id)
            await self._write_index_unlocked(index)
            return operation

    async def update_operation(self, operation: RollbackOperation) -> RollbackOperation:
        """Atomically replace an existing operation journal record and its index heartbeat."""
        operation.updated_at = datetime.now(UTC)
        async with self._lock(operation.conversation_id):
            path = self._operation_path(operation.conversation_id, operation.id)
            if not path.exists():
                raise CheckpointStoreError("rollback operation 不存在")
            _atomic_write_json(path, operation.to_dict())
            index = await self._read_index_unlocked(operation.conversation_id)
            if operation.id not in index.operation_ids:
                index.operation_ids.append(operation.id)
            await self._write_index_unlocked(index)
            return operation

    async def read_operation(
        self, conversation_id: uuid.UUID | str, operation_id: uuid.UUID | str
    ) -> RollbackOperation | None:
        path = self._operation_path(conversation_id, operation_id)
        if not path.exists():
            return None
        async with self._lock(conversation_id):
            try:
                return RollbackOperation.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise CheckpointStoreError("rollback operation 无法安全读取") from exc

    async def list_operations(self, conversation_id: uuid.UUID | str) -> list[RollbackOperation]:
        async with self._lock(conversation_id):
            index = await self._read_index_unlocked(conversation_id)
            result: list[RollbackOperation] = []
            for operation_id in index.operation_ids:
                path = self._operation_path(conversation_id, operation_id)
                if not path.exists():
                    continue
                try:
                    result.append(RollbackOperation.from_dict(json.loads(path.read_text(encoding="utf-8"))))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                    continue
            return result

    async def list_checkpoints(self, conversation_id: uuid.UUID | str) -> list[CodeCheckpoint]:
        async with self._lock(conversation_id):
            index = await self._read_index_unlocked(conversation_id)
            result: list[CodeCheckpoint] = []
            for checkpoint_id in index.checkpoint_ids:
                path = self._manifest_path(conversation_id, checkpoint_id)
                if not path.exists():
                    continue
                try:
                    result.append(CodeCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8"))))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                    continue
            return result

    async def _put_blob_unlocked(self, conversation_id: uuid.UUID | str, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = self._blob_path(conversation_id, digest)
        if not path.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive create prevents two writers from changing an immutable blob.
                with path.open("xb") as stream:
                    stream.write(content)
            except FileExistsError:
                pass
            except OSError as exc:
                raise CheckpointStoreError("checkpoint blob 写入失败") from exc
        return digest

    async def read_blob(self, conversation_id: uuid.UUID | str, sha256: str | None) -> bytes | None:
        if not sha256:
            return None
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256.lower()):
            raise CheckpointStoreError("checkpoint blob hash 非法")
        path = self._blob_path(conversation_id, sha256)
        try:
            return path.read_bytes() if path.exists() else None
        except OSError as exc:
            raise CheckpointStoreError("checkpoint blob 读取失败") from exc

    async def _load_manifest_unlocked(
        self, conversation_id: uuid.UUID | str, checkpoint_id: uuid.UUID | str
    ) -> CodeCheckpoint:
        path = self._manifest_path(conversation_id, checkpoint_id)
        if not path.exists():
            raise CheckpointStoreError("checkpoint 不存在")
        try:
            return CodeCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise CheckpointStoreError("checkpoint manifest 无法安全读取") from exc

    async def prepare_file(
        self,
        conversation_id: uuid.UUID | str,
        checkpoint_id: uuid.UUID | str,
        path: str,
        content: bytes,
        *,
        tool_call_id: str,
        planned_after_sha256: str | None = None,
    ) -> FileMutationRecord:
        async with self._lock(conversation_id):
            checkpoint = await self._load_manifest_unlocked(conversation_id, checkpoint_id)
            existing = checkpoint.files.get(path)
            if existing is None:
                blob_sha256 = await self._put_blob_unlocked(conversation_id, content)
                existing = FileMutationRecord(
                    path=path,
                    before=FileVersionRef(
                        exists=True,
                        blob_sha256=blob_sha256,
                        size_bytes=len(content),
                        content_kind=_content_kind(content),
                    ),
                    planned_after_sha256=planned_after_sha256,
                    tool_call_ids=[tool_call_id],
                    status="prepared",
                )
                checkpoint.files[path] = existing
            else:
                if tool_call_id not in existing.tool_call_ids:
                    existing.tool_call_ids.append(tool_call_id)
                if planned_after_sha256:
                    existing.planned_after_sha256 = planned_after_sha256
                existing.status = "prepared"
            _atomic_write_json(self._manifest_path(conversation_id, checkpoint_id), checkpoint.to_dict())
            return existing

    async def prepare_missing_file(
        self,
        conversation_id: uuid.UUID | str,
        checkpoint_id: uuid.UUID | str,
        path: str,
        *,
        tool_call_id: str,
        planned_after_sha256: str | None = None,
    ) -> FileMutationRecord:
        async with self._lock(conversation_id):
            checkpoint = await self._load_manifest_unlocked(conversation_id, checkpoint_id)
            existing = checkpoint.files.get(path)
            if existing is None:
                existing = FileMutationRecord(
                    path=path,
                    before=FileVersionRef(False, None, 0, "text"),
                    planned_after_sha256=planned_after_sha256,
                    tool_call_ids=[tool_call_id],
                    status="prepared",
                )
                checkpoint.files[path] = existing
            else:
                if tool_call_id not in existing.tool_call_ids:
                    existing.tool_call_ids.append(tool_call_id)
                if planned_after_sha256:
                    existing.planned_after_sha256 = planned_after_sha256
                existing.status = "prepared"
            _atomic_write_json(self._manifest_path(conversation_id, checkpoint_id), checkpoint.to_dict())
            return existing

    async def finalize_file(
        self,
        conversation_id: uuid.UUID | str,
        checkpoint_id: uuid.UUID | str,
        path: str,
        *,
        final_after_sha256: str | None,
        status: str = "applied",
    ) -> FileMutationRecord:
        if status not in {"prepared", "applied", "failed"}:
            raise ValueError("非法 mutation status")
        async with self._lock(conversation_id):
            checkpoint = await self._load_manifest_unlocked(conversation_id, checkpoint_id)
            record = checkpoint.files.get(path)
            if record is None:
                raise CheckpointStoreError("checkpoint mutation 不存在")
            record.final_after_sha256 = final_after_sha256
            record.status = status  # type: ignore[assignment]
            _atomic_write_json(self._manifest_path(conversation_id, checkpoint_id), checkpoint.to_dict())
            return record

    async def bind_graph_checkpoint(
        self, conversation_id: uuid.UUID | str, checkpoint_id: uuid.UUID | str, graph_checkpoint_id: str
    ) -> CodeCheckpoint:
        async with self._lock(conversation_id):
            checkpoint = await self._load_manifest_unlocked(conversation_id, checkpoint_id)
            checkpoint.graph_input_checkpoint_id = graph_checkpoint_id
            _atomic_write_json(self._manifest_path(conversation_id, checkpoint_id), checkpoint.to_dict())
            return checkpoint

    async def bind_graph_run(
        self,
        conversation_id: uuid.UUID | str,
        checkpoint_id: uuid.UUID | str,
        *,
        graph_parent_checkpoint_id: str | None,
        graph_parent_bound: bool,
        graph_output_checkpoint_id: str | None,
    ) -> CodeCheckpoint:
        async with self._lock(conversation_id):
            checkpoint = await self._load_manifest_unlocked(conversation_id, checkpoint_id)
            checkpoint.graph_parent_checkpoint_id = graph_parent_checkpoint_id
            checkpoint.graph_parent_bound = graph_parent_bound
            checkpoint.graph_output_checkpoint_id = graph_output_checkpoint_id
            # Keep the legacy field populated only for readers that understand the old name;
            # its value is the graph input node, never the code checkpoint UUID.
            checkpoint.graph_input_checkpoint_id = graph_parent_checkpoint_id
            _atomic_write_json(self._manifest_path(conversation_id, checkpoint_id), checkpoint.to_dict())
            return checkpoint

    async def seal_checkpoint(
        self, conversation_id: uuid.UUID | str, checkpoint_id: uuid.UUID | str, *, interrupted: bool = False
    ) -> CodeCheckpoint:
        async with self._lock(conversation_id):
            checkpoint = await self._load_manifest_unlocked(conversation_id, checkpoint_id)
            checkpoint.status = "interrupted" if interrupted else "sealed"
            checkpoint.sealed_at = datetime.now(UTC)
            _atomic_write_json(self._manifest_path(conversation_id, checkpoint_id), checkpoint.to_dict())
            return checkpoint

    async def touch(self, conversation_id: uuid.UUID | str) -> None:
        async with self._lock(conversation_id):
            await self._write_index_unlocked(await self._read_index_unlocked(conversation_id))
