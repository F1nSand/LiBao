"""Preview and execute safe checkpoint restores.

The restore service intentionally treats user/editor changes as conflicts: an AI
checkpoint may only replace a file when its current hash is the hash recorded by
the mutation gateway.  This is the key property that keeps manual edits safe.
"""

from __future__ import annotations

import difflib
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.checkpoints.identity import workspace_identity_matches
from app.checkpoints.models import (
    CodeCheckpoint,
    ConversationCursor,
    FileRestoreResult,
    FileVersionRef,
    RollbackMode,
    RollbackOperation,
)
from app.checkpoints.runtime import get_checkpoint_service
from app.core.config import get_settings
from app.core.errors import AppError
from app.storage.models.conversation import Conversation
from app.storage.repositories.message import MessageRepository
from app.storage.repositories.task import TaskRepository


class RestoreConflict(AppError):
    def __init__(self, message: str = "当前会话有正在执行的任务，请先取消后重试") -> None:
        super().__init__(40901, message)


_PREVIEWS: dict[str, dict[str, Any]] = {}
_PREVIEW_TTL = timedelta(minutes=10)


def _sha256(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _cursor(conversation: Conversation) -> ConversationCursor:
    return ConversationCursor(
        active_message_head_id=conversation.active_message_head_id,
        message_cursor_initialized=conversation.message_cursor_initialized,
        active_graph_checkpoint_id=conversation.active_graph_checkpoint_id,
        active_code_node_id=conversation.active_code_node_id,
        history_revision=conversation.history_revision,
    )


def _write_atomic(path: Path, payload: bytes) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".restore.tmp")
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


class CheckpointRestoreService:
    def __init__(self, checkpoint_service: Any | None = None) -> None:
        if checkpoint_service is not None:
            self.checkpoints = checkpoint_service
        else:
            settings = get_settings()
            self.checkpoints = get_checkpoint_service(settings.agent_data_dir, settings.checkpoint_retention_days)

    async def _active_tasks(self, db: Any, conversation_id: uuid.UUID) -> list[Any]:
        tasks = await TaskRepository(db).table.list(limit=None)
        return [
            task
            for task in tasks
            if task.deleted_at is None
            and str((task.input or {}).get("conversation_id") or "") == str(conversation_id)
            and task.status in {"pending", "running", "waiting_confirm"}
        ]

    async def _assert_idle(self, db: Any, conversation: Conversation) -> None:
        tasks = await self._active_tasks(db, conversation.id)
        if tasks:
            raise RestoreConflict()

    async def _file_plan(
        self,
        conversation_id: uuid.UUID,
        target: CodeCheckpoint,
        root: Path,
    ) -> tuple[list[dict[str, Any]], dict[str, FileVersionRef]]:
        checkpoints = await self.checkpoints.store.list_checkpoints(conversation_id)
        # A previous rollback is itself an AI-owned workspace transition.  When the
        # user switches back to a later node, the current bytes may therefore differ
        # from that node's post-image without being a manual edit.  Keep the hashes
        # produced by completed rollback operations as trusted transition states;
        # all other unexpected hashes remain conflicts and are skipped.
        known_rollback_hashes: dict[str, set[str | None]] = {}
        for operation in await self.checkpoints.store.list_operations(conversation_id):
            if operation.status not in {"completed", "partial"}:
                continue
            for result in operation.file_results:
                if result.action in {"restored", "deleted"}:
                    known_rollback_hashes.setdefault(result.path, set()).add(result.target_sha256)
        try:
            target_index = next(i for i, item in enumerate(checkpoints) if item.id == target.id)
        except StopIteration as exc:
            raise AppError(40431, "checkpoint 不存在或已过期") from exc
        target_refs: dict[str, FileVersionRef] = {}
        expected: dict[str, str | None] = {}
        expected_exists: dict[str, bool] = {}
        for checkpoint in checkpoints[target_index:]:
            for path, mutation in checkpoint.files.items():
                target_refs.setdefault(path, mutation.before)
                expected[path] = mutation.final_after_sha256 or mutation.planned_after_sha256
                expected_exists[path] = expected[path] is not None
        rows: list[dict[str, Any]] = []
        for path, target_ref in sorted(target_refs.items()):
            target_path = root / Path(path)
            current = target_path.read_bytes() if target_path.is_file() else None
            current_sha = _sha256(current)
            expected_sha = expected.get(path)
            trusted_transition = current_sha in known_rollback_hashes.get(path, set())
            conflict = (
                False
                if trusted_transition
                else ((current_sha != expected_sha) if expected_exists.get(path, False) else current is not None)
            )
            action = "skip_conflict" if conflict else ("delete" if not target_ref.exists else "restore")
            item: dict[str, Any] = {
                "path": path,
                "action": action,
                "content_kind": target_ref.content_kind,
                "current_sha256": current_sha,
                "target_sha256": target_ref.blob_sha256,
                "current_size": len(current) if current is not None else 0,
                "target_size": target_ref.size_bytes,
                "expected_exists": expected_exists.get(path, False),
                "conflict": conflict,
                "reason": "文件在 checkpoint 后被手动或外部修改" if conflict else None,
            }
            if not conflict and current is not None and target_ref.exists:
                target_bytes = await self.checkpoints.store.read_blob(conversation_id, target_ref.blob_sha256)
                if target_bytes is not None and len(current) <= 1024 * 1024 and len(target_bytes) <= 1024 * 1024:
                    try:
                        left = current.decode("utf-8")
                        right = target_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        pass
                    else:
                        diff = "".join(
                            difflib.unified_diff(
                                left.splitlines(keepends=True),
                                right.splitlines(keepends=True),
                                fromfile=f"a/{path}",
                                tofile=f"b/{path}",
                                n=3,
                            )
                        )
                        item["diff"] = diff[:200 * 1024]
                        item["diff_truncated"] = len(diff) > 200 * 1024
            rows.append(item)
        return rows, target_refs

    async def preview_checkpoint(
        self,
        db: Any,
        conversation: Conversation,
        *,
        target_checkpoint_id: uuid.UUID,
        mode: RollbackMode,
        workspace_root: str | None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        if mode not in {"code_only", "conversation_only", "both"}:
            raise AppError(40031, "不支持的回滚模式")
        await self._assert_idle(db, conversation)
        target = await self.checkpoints.store.read_checkpoint(conversation.id, target_checkpoint_id)
        if target is None:
            raise AppError(40431, "checkpoint 不存在或已过期")
        files: list[dict[str, Any]] = []
        target_refs: dict[str, FileVersionRef] = {}
        if mode in {"code_only", "both"}:
            if not workspace_root or not workspace_identity_matches(
                target.workspace_identity, workspace_root, workspace_id
            ):
                raise AppError(40932, "checkpoint 与当前工作区不匹配")
            files, target_refs = await self._file_plan(conversation.id, target, Path(workspace_root))
        messages = await MessageRepository(db).list_active(
            conversation.id,
            conversation.active_message_head_id,
            cursor_initialized=conversation.message_cursor_initialized,
            limit=None,
            offset=0,
        )
        try:
            target_position = next(i for i, message in enumerate(messages) if message.id == target.user_message_id)
        except StopIteration:
            target_position = len(messages) - 1
        hidden = max(0, len(messages) - target_position - 1)
        preview_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + _PREVIEW_TTL
        payload = {
            "preview_id": str(preview_id),
            "target": {"type": "checkpoint", "id": str(target.id)},
            "mode": mode,
            "target_message_id": str(target.user_message_id),
            "target_checkpoint_id": str(target.id),
            "expires_at": expires_at.isoformat(),
            "conversation_revision": conversation.history_revision,
            "conversation": {
                "truncate_after_message_id": str(target.user_message_id),
                "hidden_message_count": hidden if mode in {"conversation_only", "both"} else 0,
            },
            "files": files if mode in {"code_only", "both"} else [],
            "warnings": [
                "仅恢复 AI 直接文件工具产生的工作区文件；手动编辑/外部进程冲突文件将跳过。",
                "shell、脚本、数据库、MCP/远程服务、记忆和知识库副作用不纳入回滚。",
            ],
        }
        _PREVIEWS[str(preview_id)] = {
            **payload,
            "conversation_id": str(conversation.id),
            "workspace_root": workspace_root,
            "workspace_id": workspace_id,
            "target_refs": target_refs,
        }
        return payload

    async def execute_preview(self, db: Any, conversation: Conversation, preview_id: uuid.UUID) -> dict[str, Any]:
        record = _PREVIEWS.get(str(preview_id))
        if record is None:
            raise AppError(40933, "preview 不存在或已过期，请重新预览")
        expires_at = datetime.fromisoformat(record["expires_at"])
        if expires_at < datetime.now(UTC):
            _PREVIEWS.pop(str(preview_id), None)
            raise AppError(40933, "preview 不存在或已过期，请重新预览")
        if record.get("conversation_id") != str(conversation.id):
            raise AppError(40935, "preview 与当前会话不匹配")
        if record.get("conversation_revision") != conversation.history_revision:
            raise AppError(40934, "会话已发生变化，请重新预览")
        await self._assert_idle(db, conversation)
        if record.get("kind") == "operation_before":
            return await self._execute_operation_preview(db, conversation, record, preview_id)
        mode = record["mode"]
        root: Path | None = None
        if mode in {"code_only", "both"}:
            workspace_root = record.get("workspace_root")
            if not workspace_root:
                raise AppError(40932, "checkpoint 与当前工作区不匹配")
            root = Path(workspace_root)
        target_id = uuid.UUID(record["target_checkpoint_id"])
        target = await self.checkpoints.store.read_checkpoint(conversation.id, target_id)
        if target is None:
            raise AppError(40431, "checkpoint 不存在或已过期")
        target_refs: dict[str, FileVersionRef] = {}
        files: list[dict[str, Any]] = []
        if root is not None:
            files, target_refs = await self._file_plan(conversation.id, target, root)
        before_cursor = _cursor(conversation)
        undo_files: dict[str, FileVersionRef] = {}
        results: list[FileRestoreResult] = []
        restored = deleted = conflicts = 0
        for item in files:
            assert root is not None
            path = root / Path(item["path"])
            current = path.read_bytes() if path.is_file() else None
            current_sha = _sha256(current)
            expected_sha = item.get("current_sha256")
            expected_exists = bool(item.get("expected_exists"))
            if item.get("conflict") or (
                current_sha != expected_sha if expected_exists else current is not None
            ):
                conflicts += 1
                results.append(
                    FileRestoreResult(
                        item["path"],
                        "skipped_conflict",
                        "文件在预览后发生变化",
                        current_sha,
                        item.get("target_sha256"),
                    )
                )
                continue
            if current is not None:
                async with self.checkpoints.store._lock(conversation.id):  # noqa: SLF001
                    digest = await self.checkpoints.store._put_blob_unlocked(conversation.id, current)  # noqa: SLF001
                undo_files[item["path"]] = FileVersionRef(True, digest, len(current), item["content_kind"])
            else:
                undo_files[item["path"]] = FileVersionRef(False, None, 0, item["content_kind"])
            target_ref = target_refs[item["path"]]
            if target_ref.exists:
                target_bytes = await self.checkpoints.store.read_blob(conversation.id, target_ref.blob_sha256)
                if target_bytes is None:
                    raise AppError(50031, "checkpoint blob 缺失，已安全停止恢复")
                _write_atomic(path, target_bytes)
                restored += 1
                results.append(FileRestoreResult(item["path"], "restored", None, current_sha, target_ref.blob_sha256))
            else:
                path.unlink(missing_ok=True)
                deleted += 1
                results.append(FileRestoreResult(item["path"], "deleted", None, current_sha, None))

        after_cursor = _cursor(conversation)
        if mode in {"conversation_only", "both"}:
            conversation.active_message_head_id = target.user_message_id
            conversation.active_graph_checkpoint_id = target.graph_input_checkpoint_id
            conversation.active_code_node_id = target.id
            conversation.history_revision += 1
        elif mode == "code_only":
            conversation.active_code_node_id = target.id
        after_cursor = _cursor(conversation)
        operation = RollbackOperation(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            target_checkpoint_id=target.id,
            mode=mode,
            before_cursor=before_cursor,
            after_cursor=after_cursor,
            undo_files=undo_files,
            file_results=results,
            status="partial" if conflicts else "completed",
        )
        await self.checkpoints.store.create_operation(operation)
        await db.commit()
        _PREVIEWS.pop(str(preview_id), None)
        return {
            "operation_id": str(operation.id),
            "status": operation.status,
            "restored_files": restored,
            "deleted_files": deleted,
            "skipped_conflicts": [r.path for r in results if r.action == "skipped_conflict"],
            "hidden_message_count": record["conversation"]["hidden_message_count"],
            "undo_available": True,
            "history_revision": conversation.history_revision,
        }

    async def preview_operation_before(
        self, db: Any, conversation: Conversation, operation_id: uuid.UUID, workspace_root: str
    ) -> dict[str, Any]:
        await self._assert_idle(db, conversation)
        operation = await self.checkpoints.store.read_operation(conversation.id, operation_id)
        if operation is None:
            raise AppError(40432, "rollback operation 不存在")
        files: list[dict[str, Any]] = []
        for path, target_ref in sorted(operation.undo_files.items()):
            target_path = Path(workspace_root) / Path(path)
            current = target_path.read_bytes() if target_path.is_file() else None
            current_sha = _sha256(current)
            original_result = next((item for item in operation.file_results if item.path == path), None)
            expected_sha = original_result.target_sha256 if original_result else None
            expected_exists = original_result is not None and original_result.action != "deleted"
            conflict = (current_sha != expected_sha) if expected_exists else current is not None
            item = {
                "path": path,
                "action": "skip_conflict" if conflict else ("delete" if not target_ref.exists else "restore"),
                "content_kind": target_ref.content_kind,
                "current_sha256": current_sha,
                "target_sha256": target_ref.blob_sha256,
                "current_size": len(current) if current is not None else 0,
                "target_size": target_ref.size_bytes,
                "expected_exists": expected_exists,
                "conflict": conflict,
                "reason": "文件在上次恢复后被手动或外部修改" if conflict else None,
            }
            files.append(item)
        preview_id = uuid.uuid4()
        payload = {
            "preview_id": str(preview_id),
            "target": {"type": "rollback_operation_before", "id": str(operation.id)},
            "mode": operation.mode,
            "target_message_id": (
                str(operation.before_cursor.active_message_head_id)
                if operation.before_cursor.active_message_head_id
                else None
            ),
            "conversation_revision": conversation.history_revision,
            "expires_at": (datetime.now(UTC) + _PREVIEW_TTL).isoformat(),
            "conversation": {"truncate_after_message_id": None, "hidden_message_count": 0},
            "files": files,
            "warnings": [
                "仅恢复 AI 直接文件工具产生的工作区文件；手动编辑/外部进程冲突文件将跳过。",
                "shell、脚本、数据库、MCP/远程服务、记忆和知识库副作用不纳入回滚。",
            ],
        }
        _PREVIEWS[str(preview_id)] = {
            **payload,
            "kind": "operation_before",
            "conversation_id": str(conversation.id),
            "workspace_root": workspace_root,
            "operation_id": str(operation.id),
            "operation": operation,
        }
        return payload

    async def _execute_operation_preview(
        self, db: Any, conversation: Conversation, record: dict[str, Any], preview_id: uuid.UUID
    ) -> dict[str, Any]:
        operation: RollbackOperation = record["operation"]
        root = Path(record["workspace_root"])
        before_cursor = _cursor(conversation)
        undo_files: dict[str, FileVersionRef] = {}
        results: list[FileRestoreResult] = []
        restored = deleted = conflicts = 0
        for item in record["files"]:
            path = root / Path(item["path"])
            current = path.read_bytes() if path.is_file() else None
            current_sha = _sha256(current)
            expected_sha = item.get("current_sha256")
            expected_exists = bool(item.get("expected_exists"))
            if item.get("conflict") or (current_sha != expected_sha if expected_exists else current is not None):
                conflicts += 1
                results.append(
                    FileRestoreResult(
                        item["path"],
                        "skipped_conflict",
                        "文件在预览后发生变化",
                        current_sha,
                        item.get("target_sha256"),
                    )
                )
                continue
            if current is not None:
                async with self.checkpoints.store._lock(conversation.id):  # noqa: SLF001
                    digest = await self.checkpoints.store._put_blob_unlocked(conversation.id, current)  # noqa: SLF001
                undo_files[item["path"]] = FileVersionRef(True, digest, len(current), item["content_kind"])
            else:
                undo_files[item["path"]] = FileVersionRef(False, None, 0, item["content_kind"])
            target_ref = operation.undo_files[item["path"]]
            if target_ref.exists:
                content = await self.checkpoints.store.read_blob(conversation.id, target_ref.blob_sha256)
                if content is None:
                    raise AppError(50031, "rollback blob 缺失，已安全停止恢复")
                _write_atomic(path, content)
                restored += 1
                results.append(FileRestoreResult(item["path"], "restored", None, current_sha, target_ref.blob_sha256))
            else:
                path.unlink(missing_ok=True)
                deleted += 1
                results.append(FileRestoreResult(item["path"], "deleted", None, current_sha, None))
        desired = operation.before_cursor
        conversation.active_message_head_id = desired.active_message_head_id
        conversation.active_graph_checkpoint_id = desired.active_graph_checkpoint_id
        conversation.active_code_node_id = desired.active_code_node_id
        conversation.history_revision += 1
        after_cursor = _cursor(conversation)
        inverse = RollbackOperation(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            target_checkpoint_id=operation.target_checkpoint_id,
            mode=operation.mode,
            before_cursor=before_cursor,
            after_cursor=after_cursor,
            undo_files=undo_files,
            file_results=results,
            status="partial" if conflicts else "completed",
        )
        await self.checkpoints.store.create_operation(inverse)
        await db.commit()
        _PREVIEWS.pop(str(preview_id), None)
        return {
            "operation_id": str(inverse.id),
            "status": inverse.status,
            "restored_files": restored,
            "deleted_files": deleted,
            "skipped_conflicts": [r.path for r in results if r.action == "skipped_conflict"],
            "hidden_message_count": 0,
            "undo_available": True,
            "history_revision": conversation.history_revision,
        }
