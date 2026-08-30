"""Preview and execute safe checkpoint restores.

The restore service intentionally treats user/editor changes as conflicts: an AI
checkpoint may only replace a file when its current hash is the hash recorded by
the mutation gateway.  This is the key property that keeps manual edits safe.
"""

from __future__ import annotations

import contextlib
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
from app.storage.models.message import Message
from app.storage.repositories.attachment import AttachmentRepository
from app.storage.repositories.message import MessageRepository
from app.storage.repositories.task import TaskRepository


class RestoreConflict(AppError):
    def __init__(self, message: str = "当前会话有正在执行的任务，请先取消后重试") -> None:
        super().__init__(40901, message)


_PREVIEWS: dict[str, dict[str, Any]] = {}
_PREVIEW_TTL = timedelta(minutes=10)
_RESTORE_LOCKS: dict[str, Any] = {}


def _restore_lock(conversation_id: uuid.UUID) -> Any:
    import asyncio

    return _RESTORE_LOCKS.setdefault(str(conversation_id), asyncio.Lock())


def _sha256(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _cursor(conversation: Conversation) -> ConversationCursor:
    return ConversationCursor(
        active_message_head_id=conversation.active_message_head_id,
        message_cursor_initialized=conversation.message_cursor_initialized,
        active_graph_checkpoint_id=conversation.active_graph_checkpoint_id,
        graph_cursor_initialized=conversation.graph_cursor_initialized,
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
    def __init__(self, checkpoint_service: Any | None = None, graph_checkpoint_resolver: Any | None = None) -> None:
        if checkpoint_service is not None:
            self.checkpoints = checkpoint_service
        else:
            settings = get_settings()
            self.checkpoints = get_checkpoint_service(settings.agent_data_dir, settings.checkpoint_retention_days)
        self.graph_checkpoint_resolver = graph_checkpoint_resolver

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

    async def _assert_no_incomplete_operations(self, conversation_id: uuid.UUID) -> None:
        for operation in await self.checkpoints.store.list_operations(conversation_id):
            if operation.status in {"prepared", "applying", "failed_partial"}:
                raise AppError(40938, "存在未完成的恢复操作，请先执行 operation-before 撤销")

    async def _draft_for_message(self, db: Any, conversation: Conversation, message: Message) -> dict[str, Any]:
        """Build an authoritative composer draft without mutating attachment ownership."""
        attachments: list[dict[str, Any]] = []
        attachment_repo = AttachmentRepository(db)
        for raw_ref in message.attachments or []:
            ref = raw_ref if isinstance(raw_ref, dict) else {"attachment_id": str(raw_ref)}
            raw_id = ref.get("attachment_id") or ref.get("id")
            attachment_id = str(raw_id or "")
            row = None
            try:
                if raw_id:
                    row = await attachment_repo.get(conversation.user_id, uuid.UUID(str(raw_id)))
            except (TypeError, ValueError):
                row = None
            historical_name = ref.get("name") or ref.get("filename") or ""
            historical_mime = ref.get("mime_type") or ref.get("content_type")
            historical_size = ref.get("size")
            if row is None:
                available = False
                status = ref.get("status")
                unavailable_reason = "附件已不可用"
            else:
                available = row.status != "failed"
                status = row.status
                unavailable_reason = None if available else (row.error or "附件处理失败")
                if not historical_name:
                    historical_name = row.filename
                if not historical_mime:
                    historical_mime = row.content_type
                if historical_size is None:
                    historical_size = row.size_bytes
            attachments.append(
                {
                    "attachment_id": attachment_id,
                    "name": historical_name,
                    "mime_type": historical_mime,
                    "size": historical_size,
                    "status": status,
                    "available": available,
                    "unavailable_reason": unavailable_reason,
                }
            )
        return {
            "source_message_id": str(message.id),
            "content": message.content,
            "attachments": attachments,
            "file_refs": [dict(item) if isinstance(item, dict) else item for item in (message.file_refs or [])],
        }

    async def _resolve_graph_parent(
        self, conversation_id: uuid.UUID, target: CodeCheckpoint
    ) -> tuple[str | None, bool]:
        """Resolve a legacy input id to its actual parent, never treating input as parent."""
        if target.graph_parent_bound:
            return target.graph_parent_checkpoint_id, True
        resolver = self.graph_checkpoint_resolver
        candidate = target.graph_input_checkpoint_id or target.graph_parent_checkpoint_id
        if resolver is None or not candidate:
            return None, False
        get_tuple = getattr(resolver, "aget_tuple", None)
        if get_tuple is None:
            return None, False
        graph_tuple = await get_tuple(
            {"configurable": {"thread_id": str(conversation_id), "checkpoint_id": str(candidate)}}
        )
        if graph_tuple is None or (graph_tuple.metadata or {}).get("source") != "input":
            return None, False
        checkpoint = graph_tuple.checkpoint or {}
        raw_parent = checkpoint.get("parent_checkpoint_id")
        parent_id = str(raw_parent) if raw_parent else None
        target.graph_parent_checkpoint_id = parent_id
        target.graph_parent_bound = True
        with contextlib.suppress(Exception):
            await self.checkpoints.store.bind_graph_run(
                conversation_id,
                target.id,
                graph_parent_checkpoint_id=parent_id,
                graph_parent_bound=True,
                graph_output_checkpoint_id=target.graph_output_checkpoint_id,
            )
        return parent_id, True

    async def _conversation_plan(
        self, db: Any, conversation: Conversation, target: CodeCheckpoint, mode: RollbackMode
    ) -> dict[str, Any]:
        """Validate the checkpoint/message binding and derive the post-restore branch."""
        if mode == "code_only":
            # Code-only switching is intentionally usable for detached/future nodes,
            # including legacy manifests that predate persisted message rows.
            return {
                "action": "unchanged",
                "active_message_head_after_id": (
                    str(conversation.active_message_head_id) if conversation.active_message_head_id else None
                ),
                "withdrawn_from_message_id": None,
                "hidden_message_count": 0,
                "draft": None,
            }
        current_messages = await MessageRepository(db).list_active(
            conversation.id,
            conversation.active_message_head_id,
            cursor_initialized=conversation.message_cursor_initialized,
            limit=None,
            offset=0,
        )
        target_message = await MessageRepository(db).get_in_conversation(conversation.id, target.user_message_id)
        if target_message is None or target_message.role != "user":
            raise AppError(40936, "checkpoint 与目标用户消息不匹配")
        if (
            target_message.checkpoint_id != target.id
            or target_message.history_parent_id != target.anchor_message_head_id
        ):
            raise AppError(40936, "checkpoint 与目标用户消息不匹配")
        try:
            target_position = next(i for i, message in enumerate(current_messages) if message.id == target_message.id)
        except StopIteration as exc:
            raise AppError(40936, "目标消息不在当前会话分支") from exc
        _, graph_parent_bound = await self._resolve_graph_parent(conversation.id, target)
        if not graph_parent_bound:
            raise AppError(40937, "checkpoint 缺少可验证的对话图游标")
        hidden = max(0, len(current_messages) - target_position)
        return {
            "action": "withdraw_from_target",
            "active_message_head_after_id": (
                str(target.anchor_message_head_id) if target.anchor_message_head_id else None
            ),
            "withdrawn_from_message_id": str(target_message.id),
            "hidden_message_count": hidden,
            "draft": await self._draft_for_message(db, conversation, target_message),
        }

    def _planned_cursor(
        self, conversation: Conversation, target: CodeCheckpoint, mode: RollbackMode
    ) -> ConversationCursor:
        current = _cursor(conversation)
        message_head = current.active_message_head_id
        message_initialized = current.message_cursor_initialized
        graph_id = current.active_graph_checkpoint_id
        graph_initialized = current.graph_cursor_initialized
        code_node = current.active_code_node_id
        if mode in {"conversation_only", "both"}:
            message_head = target.anchor_message_head_id
            message_initialized = True
            graph_id = target.graph_parent_checkpoint_id
            graph_initialized = target.graph_parent_bound
        if mode in {"code_only", "both"}:
            code_node = target.id
        return ConversationCursor(
            active_message_head_id=message_head,
            message_cursor_initialized=message_initialized,
            active_graph_checkpoint_id=graph_id,
            graph_cursor_initialized=graph_initialized,
            active_code_node_id=code_node,
            history_revision=current.history_revision + 1,
        )

    @staticmethod
    def _apply_cursor(conversation: Conversation, cursor: ConversationCursor) -> None:
        conversation.active_message_head_id = cursor.active_message_head_id
        conversation.message_cursor_initialized = cursor.message_cursor_initialized
        conversation.active_graph_checkpoint_id = cursor.active_graph_checkpoint_id
        conversation.graph_cursor_initialized = cursor.graph_cursor_initialized
        conversation.active_code_node_id = cursor.active_code_node_id
        conversation.history_revision = cursor.history_revision

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
                after_state = mutation.final_after if mutation.final_after_recorded else mutation.planned_after
                if after_state is None:
                    # v1 manifests may have no explicit after-state.  Preserve the
                    # old hash interpretation only for those records.
                    expected[path] = mutation.final_after_sha256 or mutation.planned_after_sha256
                    expected_exists[path] = expected[path] is not None
                else:
                    expected[path] = after_state.sha256
                    expected_exists[path] = after_state.exists
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
        client_request_id: str | None = None,
    ) -> dict[str, Any]:
        if mode not in {"code_only", "conversation_only", "both"}:
            raise AppError(40031, "不支持的回滚模式")
        await self._assert_idle(db, conversation)
        await self._assert_no_incomplete_operations(conversation.id)
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
        conversation_plan = await self._conversation_plan(db, conversation, target, mode)
        preview_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + _PREVIEW_TTL
        payload = {
            "preview_id": str(preview_id),
            "client_request_id": str(client_request_id or uuid.uuid4()),
            "target": {
                "type": "checkpoint",
                "id": str(target.id),
                "message_id": str(target.user_message_id),
            },
            "mode": mode,
            "target_message_id": str(target.user_message_id),
            "target_checkpoint_id": str(target.id),
            "expires_at": expires_at.isoformat(),
            "conversation_revision": conversation.history_revision,
            "active_code_node_id": (
                str(conversation.active_code_node_id) if conversation.active_code_node_id else None
            ),
            "conversation": conversation_plan,
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

    async def execute_preview(
        self,
        db: Any,
        conversation: Conversation,
        preview_id: uuid.UUID,
        *,
        expected_mode: RollbackMode | None = None,
        client_request_id: str | None = None,
    ) -> dict[str, Any]:
        async with _restore_lock(conversation.id):
            return await self._execute_preview_unlocked(
                db,
                conversation,
                preview_id,
                expected_mode=expected_mode,
                client_request_id=client_request_id,
            )

    async def _execute_preview_unlocked(
        self,
        db: Any,
        conversation: Conversation,
        preview_id: uuid.UUID,
        *,
        expected_mode: RollbackMode | None = None,
        client_request_id: str | None = None,
    ) -> dict[str, Any]:
        record = _PREVIEWS.get(str(preview_id))
        if record is None:
            raise AppError(40933, "preview 不存在或已过期，请重新预览")
        record_mode = record.get("mode")
        if expected_mode is not None and expected_mode != record_mode:
            raise AppError(40936, "确认模式与预览不一致，请重新预览")
        record_request_id = record.get("client_request_id")
        if client_request_id is not None and record_request_id != str(client_request_id):
            raise AppError(40936, "确认请求与预览不一致，请重新预览")
        if record.get("conversation_id") != str(conversation.id):
            raise AppError(40935, "preview 与当前会话不匹配")
        if record.get("result") is not None:
            return record["result"]
        expires_at = datetime.fromisoformat(record["expires_at"])
        if expires_at < datetime.now(UTC):
            _PREVIEWS.pop(str(preview_id), None)
            raise AppError(40933, "preview 不存在或已过期，请重新预览")
        if record.get("conversation_revision") != conversation.history_revision:
            raise AppError(40934, "会话已发生变化，请重新预览")
        expected_code_node = record.get("active_code_node_id")
        current_code_node = str(conversation.active_code_node_id) if conversation.active_code_node_id else None
        if expected_code_node != current_code_node:
            raise AppError(40934, "会话代码节点已变化，请重新预览")
        await self._assert_idle(db, conversation)
        if record.get("kind") == "operation_before":
            return await self._execute_operation_preview(db, conversation, record, preview_id)
        await self._assert_no_incomplete_operations(conversation.id)
        mode = record_mode
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
        conversation_plan = record.get("conversation") or await self._conversation_plan(db, conversation, target, mode)
        target_refs: dict[str, FileVersionRef] = {}
        files: list[dict[str, Any]] = []
        if root is not None:
            files = list(record.get("files") or [])
            target_refs = dict(record.get("target_refs") or {})
        before_cursor = _cursor(conversation)
        planned_cursor = self._planned_cursor(conversation, target, mode)
        target_bytes: dict[str, bytes] = {}
        undo_files: dict[str, FileVersionRef] = {}
        results: list[FileRestoreResult] = []
        # Preflight every target blob and capture every undo blob before the first
        # workspace mutation.  A missing target blob therefore leaves the workspace
        # untouched and produces no half-written operation.
        for item in files:
            assert root is not None
            relative_path = item["path"]
            target_ref = target_refs.get(relative_path)
            if target_ref is None:
                raise AppError(50031, "checkpoint 文件计划缺少目标引用，已安全停止恢复")
            path = root / Path(relative_path)
            current = path.read_bytes() if path.is_file() else None
            if item.get("conflict"):
                continue
            expected_sha = item.get("current_sha256")
            expected_exists = bool(item.get("expected_exists"))
            current_sha = _sha256(current)
            if (current_sha != expected_sha) if expected_exists else current is not None:
                continue
            if current is not None:
                async with self.checkpoints.store._lock(conversation.id):  # noqa: SLF001
                    digest = await self.checkpoints.store._put_blob_unlocked(conversation.id, current)  # noqa: SLF001
                undo_files[relative_path] = FileVersionRef(True, digest, len(current), item["content_kind"])
            else:
                undo_files[relative_path] = FileVersionRef(False, None, 0, item["content_kind"])
            if target_ref.exists:
                content = await self.checkpoints.store.read_blob(conversation.id, target_ref.blob_sha256)
                if content is None:
                    raise AppError(50031, "checkpoint blob 缺失，已安全停止恢复")
                target_bytes[relative_path] = content
        operation = RollbackOperation(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            target_checkpoint_id=target.id,
            mode=mode,
            before_cursor=before_cursor,
            after_cursor=None,
            undo_files=undo_files,
            file_results=[],
            status="prepared",
            preview_id=preview_id,
            target_user_message_id=target.user_message_id,
            planned_files=list(files),
            applied_paths=[],
            planned_after_cursor=planned_cursor,
        )
        await self.checkpoints.store.create_operation(operation)
        try:
            operation.status = "applying"
            await self.checkpoints.store.update_operation(operation)
            restored = deleted = conflicts = 0
            for item in files:
                assert root is not None
                relative_path = item["path"]
                path = root / Path(relative_path)
                current = path.read_bytes() if path.is_file() else None
                current_sha = _sha256(current)
                expected_sha = item.get("current_sha256")
                expected_exists = bool(item.get("expected_exists"))
                conflict = bool(item.get("conflict")) or (
                    (current_sha != expected_sha) if expected_exists else current is not None
                )
                if conflict:
                    conflicts += 1
                    results.append(
                        FileRestoreResult(
                            relative_path,
                            "skipped_conflict",
                            "文件在预览后发生变化",
                            current_sha,
                            item.get("target_sha256"),
                        )
                    )
                    operation.file_results = list(results)
                    await self.checkpoints.store.update_operation(operation)
                    continue
                target_ref = target_refs[relative_path]
                if target_ref.exists:
                    _write_atomic(path, target_bytes[relative_path])
                    restored += 1
                    results.append(
                        FileRestoreResult(relative_path, "restored", None, current_sha, target_ref.blob_sha256)
                    )
                else:
                    path.unlink(missing_ok=True)
                    deleted += 1
                    results.append(FileRestoreResult(relative_path, "deleted", None, current_sha, None))
                operation.file_results = list(results)
                operation.applied_paths.append(relative_path)
                await self.checkpoints.store.update_operation(operation)

            # A partial workspace transition is represented by its operation id,
            # while a zero-applied conflict keeps the previous code cursor.  Message
            # and graph cursors still follow the requested target for Both.
            final_cursor = planned_cursor
            if conflicts and not operation.applied_paths:
                final_cursor = ConversationCursor(
                    active_message_head_id=planned_cursor.active_message_head_id,
                    message_cursor_initialized=planned_cursor.message_cursor_initialized,
                    active_graph_checkpoint_id=planned_cursor.active_graph_checkpoint_id,
                    graph_cursor_initialized=planned_cursor.graph_cursor_initialized,
                    active_code_node_id=before_cursor.active_code_node_id,
                    history_revision=planned_cursor.history_revision,
                )
            elif conflicts and operation.applied_paths and mode in {"code_only", "both"}:
                final_cursor = ConversationCursor(
                    active_message_head_id=planned_cursor.active_message_head_id,
                    message_cursor_initialized=planned_cursor.message_cursor_initialized,
                    active_graph_checkpoint_id=planned_cursor.active_graph_checkpoint_id,
                    graph_cursor_initialized=planned_cursor.graph_cursor_initialized,
                    active_code_node_id=operation.id,
                    history_revision=planned_cursor.history_revision,
                )
            self._apply_cursor(conversation, final_cursor)
            try:
                await db.commit()
            except BaseException:
                self._apply_cursor(conversation, before_cursor)
                await db.rollback()
                raise
            operation.after_cursor = _cursor(conversation)
            operation.status = "partial" if conflicts else "completed"
            await self.checkpoints.store.update_operation(operation)
        except BaseException as exc:
            if operation.after_cursor is None:
                operation.status = "failed_partial"
                operation.error = {"message": str(exc)[:500], "type": type(exc).__name__}
                with contextlib.suppress(Exception):
                    await self.checkpoints.store.update_operation(operation)
            raise
        result = {
            "operation_id": str(operation.id),
            "status": operation.status,
            "restored_files": restored,
            "deleted_files": deleted,
            "skipped_conflicts": [r.path for r in results if r.action == "skipped_conflict"],
            "target_message_id": str(target.user_message_id),
            "mode": mode,
            "conversation": conversation_plan,
            "hidden_message_count": conversation_plan["hidden_message_count"],
            "undo_available": True,
            "history_revision": conversation.history_revision,
        }
        result["preview_id"] = str(preview_id)
        result["client_request_id"] = record.get("client_request_id")
        record["result"] = result
        return result

    async def preview_operation_before(
        self,
        db: Any,
        conversation: Conversation,
        operation_id: uuid.UUID,
        workspace_root: str,
        *,
        client_request_id: str | None = None,
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
            "client_request_id": str(client_request_id or uuid.uuid4()),
            "target": {"type": "rollback_operation_before", "id": str(operation.id), "message_id": None},
            "mode": operation.mode,
            "target_message_id": (
                str(operation.before_cursor.active_message_head_id)
                if operation.before_cursor.active_message_head_id
                else None
            ),
            "conversation_revision": conversation.history_revision,
            "active_code_node_id": (
                str(conversation.active_code_node_id) if conversation.active_code_node_id else None
            ),
            "expires_at": (datetime.now(UTC) + _PREVIEW_TTL).isoformat(),
            "conversation": {
                "action": "restore_cursor",
                "active_message_head_after_id": (
                    str(operation.before_cursor.active_message_head_id)
                    if operation.before_cursor.active_message_head_id
                    else None
                ),
                "withdrawn_from_message_id": None,
                "hidden_message_count": 0,
                "draft": None,
            },
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
        desired = operation.before_cursor
        planned_cursor = ConversationCursor(
            active_message_head_id=desired.active_message_head_id,
            message_cursor_initialized=desired.message_cursor_initialized,
            active_graph_checkpoint_id=desired.active_graph_checkpoint_id,
            graph_cursor_initialized=desired.graph_cursor_initialized,
            active_code_node_id=desired.active_code_node_id,
            history_revision=before_cursor.history_revision + 1,
        )
        target_bytes: dict[str, bytes] = {}
        undo_files: dict[str, FileVersionRef] = {}
        results: list[FileRestoreResult] = []
        # Validate every stored undo blob and capture the current bytes before the
        # first reverse write.  Operation-before therefore follows the same WAL
        # preflight guarantee as a forward restore.
        for item in record["files"]:
            relative_path = item["path"]
            path = root / Path(item["path"])
            current = path.read_bytes() if path.is_file() else None
            current_sha = _sha256(current)
            expected_sha = item.get("current_sha256")
            expected_exists = bool(item.get("expected_exists"))
            if item.get("conflict") or ((current_sha != expected_sha) if expected_exists else current is not None):
                continue
            if current is not None:
                async with self.checkpoints.store._lock(conversation.id):  # noqa: SLF001
                    digest = await self.checkpoints.store._put_blob_unlocked(conversation.id, current)  # noqa: SLF001
                undo_files[relative_path] = FileVersionRef(True, digest, len(current), item["content_kind"])
            else:
                undo_files[relative_path] = FileVersionRef(False, None, 0, item["content_kind"])
            target_ref = operation.undo_files[relative_path]
            if target_ref.exists:
                content = await self.checkpoints.store.read_blob(conversation.id, target_ref.blob_sha256)
                if content is None:
                    raise AppError(50031, "rollback blob 缺失，已安全停止恢复")
                target_bytes[relative_path] = content
        inverse = RollbackOperation(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            target_checkpoint_id=operation.target_checkpoint_id,
            mode=operation.mode,
            before_cursor=before_cursor,
            after_cursor=None,
            undo_files=undo_files,
            file_results=[],
            status="prepared",
            preview_id=preview_id,
            target_user_message_id=operation.target_user_message_id,
            planned_files=list(record["files"]),
            planned_after_cursor=planned_cursor,
        )
        await self.checkpoints.store.create_operation(inverse)
        try:
            inverse.status = "applying"
            await self.checkpoints.store.update_operation(inverse)
            restored = deleted = conflicts = 0
            for item in record["files"]:
                relative_path = item["path"]
                path = root / Path(relative_path)
                current = path.read_bytes() if path.is_file() else None
                current_sha = _sha256(current)
                expected_sha = item.get("current_sha256")
                expected_exists = bool(item.get("expected_exists"))
                conflict = bool(item.get("conflict")) or (
                    (current_sha != expected_sha) if expected_exists else current is not None
                )
                if conflict:
                    conflicts += 1
                    results.append(
                        FileRestoreResult(
                            relative_path,
                            "skipped_conflict",
                            "文件在预览后发生变化",
                            current_sha,
                            item.get("target_sha256"),
                        )
                    )
                    inverse.file_results = list(results)
                    await self.checkpoints.store.update_operation(inverse)
                    continue
                target_ref = operation.undo_files[relative_path]
                if target_ref.exists:
                    _write_atomic(path, target_bytes[relative_path])
                    restored += 1
                    results.append(
                        FileRestoreResult(relative_path, "restored", None, current_sha, target_ref.blob_sha256)
                    )
                else:
                    path.unlink(missing_ok=True)
                    deleted += 1
                    results.append(FileRestoreResult(relative_path, "deleted", None, current_sha, None))
                inverse.file_results = list(results)
                inverse.applied_paths.append(relative_path)
                await self.checkpoints.store.update_operation(inverse)
            self._apply_cursor(conversation, planned_cursor)
            try:
                await db.commit()
            except BaseException:
                self._apply_cursor(conversation, before_cursor)
                await db.rollback()
                raise
            inverse.after_cursor = _cursor(conversation)
            inverse.status = "partial" if conflicts else "completed"
            await self.checkpoints.store.update_operation(inverse)
        except BaseException as exc:
            if inverse.after_cursor is None:
                inverse.status = "failed_partial"
                inverse.error = {"message": str(exc)[:500], "type": type(exc).__name__}
                with contextlib.suppress(Exception):
                    await self.checkpoints.store.update_operation(inverse)
            raise
        result = {
            "operation_id": str(inverse.id),
            "status": inverse.status,
            "restored_files": restored,
            "deleted_files": deleted,
            "skipped_conflicts": [r.path for r in results if r.action == "skipped_conflict"],
            "target_message_id": None,
            "mode": operation.mode,
            "conversation": {
                "action": "restore_cursor",
                "active_message_head_after_id": (
                    str(desired.active_message_head_id) if desired.active_message_head_id else None
                ),
                "withdrawn_from_message_id": None,
                "hidden_message_count": 0,
                "draft": None,
            },
            "hidden_message_count": 0,
            "undo_available": True,
            "history_revision": conversation.history_revision,
        }
        result["preview_id"] = str(preview_id)
        result["client_request_id"] = record.get("client_request_id")
        record["result"] = result
        return result
