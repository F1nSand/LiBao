"""消息级代码 checkpoint 的纯数据模型。

模型只描述可持久化的数据，不依赖 FastAPI、LangGraph 或工作区实现；blob 内容始终
在 store 中按 bytes 读写，因而文本和二进制文件共享同一条恢复路径。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

CheckpointStatus = Literal["open", "sealed", "interrupted", "expired"]
MutationStatus = Literal["prepared", "applied", "failed"]
ContentKind = Literal["text", "binary"]
RollbackMode = Literal["code_only", "conversation_only", "both"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass(frozen=True)
class FileVersionRef:
    exists: bool
    blob_sha256: str | None
    size_bytes: int
    content_kind: ContentKind

    def to_dict(self) -> dict[str, Any]:
        return {
            "exists": self.exists,
            "blob_sha256": self.blob_sha256,
            "size_bytes": self.size_bytes,
            "content_kind": self.content_kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileVersionRef:
        return cls(
            exists=bool(data.get("exists")),
            blob_sha256=str(data["blob_sha256"]) if data.get("blob_sha256") else None,
            size_bytes=max(0, int(data.get("size_bytes") or 0)),
            content_kind="binary" if data.get("content_kind") == "binary" else "text",
        )


@dataclass(frozen=True)
class FileAfterState:
    """Observed post-mutation state; the bytes remain addressable only via before/undo refs."""

    exists: bool
    sha256: str | None
    size_bytes: int | None = None
    content_kind: ContentKind | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "exists": self.exists,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "content_kind": self.content_kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileAfterState:
        kind = data.get("content_kind")
        return cls(
            exists=bool(data.get("exists")),
            sha256=str(data["sha256"]) if data.get("sha256") else None,
            size_bytes=(max(0, int(data["size_bytes"])) if data.get("size_bytes") is not None else None),
            content_kind="binary" if kind == "binary" else "text" if kind == "text" else None,
        )


@dataclass
class FileMutationRecord:
    path: str
    before: FileVersionRef
    planned_after_sha256: str | None = None
    final_after_sha256: str | None = None
    tool_call_ids: list[str] = field(default_factory=list)
    status: MutationStatus = "prepared"
    planned_after: FileAfterState | None = None
    final_after: FileAfterState | None = None
    final_after_recorded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "before": self.before.to_dict(),
            "planned_after_sha256": self.planned_after_sha256,
            "final_after_sha256": self.final_after_sha256,
            "tool_call_ids": list(self.tool_call_ids),
            "status": self.status,
            "planned_after": self.planned_after.to_dict() if self.planned_after else None,
            "final_after": self.final_after.to_dict() if self.final_after else None,
            "final_after_recorded": self.final_after_recorded,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileMutationRecord:
        status = data.get("status")
        if status not in {"prepared", "applied", "failed"}:
            status = "prepared"
        status_value = status
        planned_sha = str(data["planned_after_sha256"]) if data.get("planned_after_sha256") else None
        final_sha = str(data["final_after_sha256"]) if data.get("final_after_sha256") else None
        planned_after = (
            FileAfterState.from_dict(data["planned_after"])
            if isinstance(data.get("planned_after"), dict)
            else FileAfterState(exists=planned_sha is not None, sha256=planned_sha)
        )
        final_recorded = (
            bool(data.get("final_after_recorded"))
            if "final_after_recorded" in data
            else status_value in {"applied", "failed"}
        )
        final_after = (
            FileAfterState.from_dict(data["final_after"])
            if isinstance(data.get("final_after"), dict)
            else (FileAfterState(exists=final_sha is not None, sha256=final_sha) if final_recorded else None)
        )
        return cls(
            path=str(data.get("path") or ""),
            before=FileVersionRef.from_dict(data.get("before") or {}),
            planned_after_sha256=planned_sha,
            final_after_sha256=final_sha,
            tool_call_ids=[str(v) for v in (data.get("tool_call_ids") or [])],
            status=status,
            planned_after=planned_after,
            final_after=final_after,
            final_after_recorded=final_recorded,
        )


@dataclass
class CodeCheckpoint:
    id: uuid.UUID
    conversation_id: uuid.UUID
    user_message_id: uuid.UUID
    workspace_identity: str
    anchor_message_head_id: uuid.UUID | None
    graph_input_checkpoint_id: str | None = None
    graph_parent_checkpoint_id: str | None = None
    graph_parent_bound: bool = False
    graph_output_checkpoint_id: str | None = None
    status: CheckpointStatus = "open"
    files: dict[str, FileMutationRecord] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
    sealed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "id": str(self.id),
            "conversation_id": str(self.conversation_id),
            "user_message_id": str(self.user_message_id),
            "workspace_identity": self.workspace_identity,
            "anchor_message_head_id": (
                str(self.anchor_message_head_id) if self.anchor_message_head_id is not None else None
            ),
            "graph_input_checkpoint_id": self.graph_input_checkpoint_id,
            "graph_parent_checkpoint_id": self.graph_parent_checkpoint_id,
            "graph_parent_bound": self.graph_parent_bound,
            "graph_output_checkpoint_id": self.graph_output_checkpoint_id,
            "status": self.status,
            "files": {path: record.to_dict() for path, record in self.files.items()},
            "created_at": _dt(self.created_at),
            "sealed_at": _dt(self.sealed_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodeCheckpoint:
        try:
            status = data.get("status")
            if status not in {"open", "sealed", "interrupted", "expired"}:
                status = "interrupted"
            files = {
                str(path): FileMutationRecord.from_dict(record)
                for path, record in (data.get("files") or {}).items()
                if isinstance(record, dict)
            }
            return cls(
                id=uuid.UUID(str(data["id"])),
                conversation_id=uuid.UUID(str(data["conversation_id"])),
                user_message_id=uuid.UUID(str(data["user_message_id"])),
                workspace_identity=str(data.get("workspace_identity") or ""),
                anchor_message_head_id=(
                    uuid.UUID(str(data["anchor_message_head_id"]))
                    if data.get("anchor_message_head_id")
                    else None
                ),
                graph_input_checkpoint_id=(
                    str(data["graph_input_checkpoint_id"]) if data.get("graph_input_checkpoint_id") else None
                ),
                graph_parent_checkpoint_id=(
                    str(data["graph_parent_checkpoint_id"])
                    if data.get("graph_parent_checkpoint_id")
                    else None
                ),
                graph_parent_bound=bool(data.get("graph_parent_bound", False)),
                graph_output_checkpoint_id=(
                    str(data["graph_output_checkpoint_id"])
                    if data.get("graph_output_checkpoint_id")
                    else None
                ),
                status=status,
                files=files,
                created_at=_parse_dt(data.get("created_at")) or _utcnow(),
                sealed_at=_parse_dt(data.get("sealed_at")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("代码 checkpoint manifest 无效") from exc


@dataclass
class CheckpointIndex:
    conversation_id: uuid.UUID
    checkpoint_ids: list[uuid.UUID] = field(default_factory=list)
    operation_ids: list[uuid.UUID] = field(default_factory=list)
    last_active_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "conversation_id": str(self.conversation_id),
            "checkpoint_ids": [str(v) for v in self.checkpoint_ids],
            "operation_ids": [str(v) for v in self.operation_ids],
            "last_active_at": _dt(self.last_active_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], conversation_id: uuid.UUID) -> CheckpointIndex:
        def parse_ids(values: Any) -> list[uuid.UUID]:
            out: list[uuid.UUID] = []
            for value in values or []:
                try:
                    out.append(uuid.UUID(str(value)))
                except (TypeError, ValueError):
                    continue
            return out

        return cls(
            conversation_id=conversation_id,
            checkpoint_ids=parse_ids(data.get("checkpoint_ids")),
            operation_ids=parse_ids(data.get("operation_ids")),
            last_active_at=_parse_dt(data.get("last_active_at")) or _utcnow(),
        )


@dataclass
class ConversationCursor:
    active_message_head_id: uuid.UUID | None
    active_graph_checkpoint_id: str | None
    active_code_node_id: uuid.UUID | None
    history_revision: int
    message_cursor_initialized: bool = False
    graph_cursor_initialized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_message_head_id": str(self.active_message_head_id) if self.active_message_head_id else None,
            "active_graph_checkpoint_id": self.active_graph_checkpoint_id,
            "active_code_node_id": str(self.active_code_node_id) if self.active_code_node_id else None,
            "history_revision": self.history_revision,
            "message_cursor_initialized": self.message_cursor_initialized,
            "graph_cursor_initialized": self.graph_cursor_initialized,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationCursor:
        def parse_uuid(value: Any) -> uuid.UUID | None:
            try:
                return uuid.UUID(str(value)) if value else None
            except (TypeError, ValueError):
                return None

        return cls(
            active_message_head_id=parse_uuid(data.get("active_message_head_id")),
            active_graph_checkpoint_id=data.get("active_graph_checkpoint_id"),
            active_code_node_id=parse_uuid(data.get("active_code_node_id")),
            history_revision=int(data.get("history_revision", 0)),
            message_cursor_initialized=bool(data.get("message_cursor_initialized", False)),
            graph_cursor_initialized=bool(data.get("graph_cursor_initialized", False)),
        )


@dataclass
class FileRestoreResult:
    path: str
    action: Literal["restored", "deleted", "skipped_conflict", "failed"]
    reason: str | None = None
    current_sha256: str | None = None
    target_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "action": self.action,
            "reason": self.reason,
            "current_sha256": self.current_sha256,
            "target_sha256": self.target_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileRestoreResult:
        return cls(
            path=str(data.get("path", "")),
            action=data.get("action", "failed"),
            reason=data.get("reason"),
            current_sha256=data.get("current_sha256"),
            target_sha256=data.get("target_sha256"),
        )


@dataclass
class RollbackOperation:
    id: uuid.UUID
    conversation_id: uuid.UUID
    target_checkpoint_id: uuid.UUID
    mode: RollbackMode
    before_cursor: ConversationCursor
    after_cursor: ConversationCursor | None
    undo_files: dict[str, FileVersionRef]
    file_results: list[FileRestoreResult]
    status: Literal["prepared", "applying", "completed", "partial", "failed_partial"]
    created_at: datetime = field(default_factory=_utcnow)
    preview_id: uuid.UUID | None = None
    target_user_message_id: uuid.UUID | None = None
    planned_files: list[dict[str, Any]] = field(default_factory=list)
    applied_paths: list[str] = field(default_factory=list)
    planned_after_cursor: ConversationCursor | None = None
    error: dict[str, Any] | None = None
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "id": str(self.id),
            "conversation_id": str(self.conversation_id),
            "target_checkpoint_id": str(self.target_checkpoint_id),
            "mode": self.mode,
            "before_cursor": self.before_cursor.to_dict(),
            "after_cursor": self.after_cursor.to_dict() if self.after_cursor else None,
            "undo_files": {path: ref.to_dict() for path, ref in self.undo_files.items()},
            "file_results": [item.to_dict() for item in self.file_results],
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "preview_id": str(self.preview_id) if self.preview_id else None,
            "target_user_message_id": str(self.target_user_message_id) if self.target_user_message_id else None,
            "planned_files": list(self.planned_files),
            "applied_paths": list(self.applied_paths),
            "planned_after_cursor": self.planned_after_cursor.to_dict() if self.planned_after_cursor else None,
            "error": self.error,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RollbackOperation:
        return cls(
            id=uuid.UUID(str(data["id"])),
            conversation_id=uuid.UUID(str(data["conversation_id"])),
            target_checkpoint_id=uuid.UUID(str(data["target_checkpoint_id"])),
            mode=data.get("mode", "both"),
            before_cursor=ConversationCursor.from_dict(data.get("before_cursor") or {}),
            after_cursor=(
                ConversationCursor.from_dict(data["after_cursor"]) if data.get("after_cursor") else None
            ),
            undo_files={path: FileVersionRef.from_dict(ref) for path, ref in (data.get("undo_files") or {}).items()},
            file_results=[FileRestoreResult.from_dict(item) for item in data.get("file_results") or []],
            status=data.get("status", "failed_partial"),
            created_at=_parse_dt(data.get("created_at")) or _utcnow(),
            preview_id=(uuid.UUID(str(data["preview_id"])) if data.get("preview_id") else None),
            target_user_message_id=(
                uuid.UUID(str(data["target_user_message_id"])) if data.get("target_user_message_id") else None
            ),
            planned_files=[dict(item) for item in data.get("planned_files") or [] if isinstance(item, dict)],
            applied_paths=[str(path) for path in data.get("applied_paths") or []],
            planned_after_cursor=(
                ConversationCursor.from_dict(data["planned_after_cursor"])
                if data.get("planned_after_cursor")
                else None
            ),
            error=dict(data["error"]) if isinstance(data.get("error"), dict) else None,
            updated_at=_parse_dt(data.get("updated_at")) or _parse_dt(data.get("created_at")) or _utcnow(),
        )
