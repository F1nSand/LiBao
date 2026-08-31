"""代码 checkpoint 领域服务（Task 1 基础）。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from app.checkpoints.models import CodeCheckpoint
from app.checkpoints.store import CodeCheckpointStore


class CheckpointService:
    def __init__(self, store: CodeCheckpointStore, *, retention_days: int = 30) -> None:
        if retention_days <= 0:
            raise ValueError("retention_days 必须为正数")
        self.store = store
        self.retention_days = retention_days

    async def create_anchor(
        self,
        *,
        conversation_id: uuid.UUID,
        user_message_id: uuid.UUID,
        workspace_identity: str,
        anchor_message_head_id: uuid.UUID,
        checkpoint_id: uuid.UUID | None = None,
        graph_parent_checkpoint_id: str | None = None,
        graph_parent_bound: bool = False,
    ) -> CodeCheckpoint:
        checkpoint = CodeCheckpoint(
            id=checkpoint_id or uuid.uuid4(),
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            workspace_identity=workspace_identity,
            anchor_message_head_id=anchor_message_head_id,
            graph_parent_checkpoint_id=graph_parent_checkpoint_id,
            graph_parent_bound=graph_parent_bound,
        )
        return await self.store.create_checkpoint(checkpoint)

    async def mark_interrupted_open(self, conversation_id: uuid.UUID | str) -> int:
        """启动恢复：把仍为 open 的 manifest 标记为 interrupted，保留其 WAL。"""
        count = 0
        for checkpoint in await self.store.list_checkpoints(conversation_id):
            if checkpoint.status == "open":
                await self.store.seal_checkpoint(conversation_id, checkpoint.id, interrupted=True)
                count += 1
        return count

    async def recover_open_checkpoints(self) -> int:
        """Startup crash recovery: open manifests remain usable but are marked interrupted."""
        total = 0
        if not self.store.root.is_dir():
            return total
        for session_dir in self.store.root.iterdir():
            if not session_dir.is_dir():
                continue
            try:
                total += await self.mark_interrupted_open(uuid.UUID(session_dir.name))
            except (ValueError, OSError):
                continue
        return total

    async def recover_incomplete_operations(self) -> int:
        """Mark prepared/applying journals as interrupted without touching workspace bytes."""
        total = 0
        if not self.store.root.is_dir():
            return total
        for session_dir in self.store.root.iterdir():
            if not session_dir.is_dir():
                continue
            try:
                conversation_id = uuid.UUID(session_dir.name)
            except (ValueError, AttributeError):
                continue
            for operation in await self.store.list_operations(conversation_id):
                if operation.status not in {"prepared", "applying"}:
                    continue
                planned_paths = {
                    str(item.get("path"))
                    for item in operation.planned_files
                    if isinstance(item, dict) and item.get("path")
                }
                result_paths = {result.path for result in operation.file_results}
                # If the cursor commit was durable and every planned path has a
                # durable result, the only missing step is the terminal status
                # write.  It is safe to finish that journal without touching
                # workspace bytes.  Any uncovered path (or explicit failed
                # result) remains a failed_partial operation requiring undo.
                provably_complete = (
                    operation.after_cursor is not None
                    and planned_paths.issubset(result_paths)
                    and not any(result.action == "failed" for result in operation.file_results)
                )
                if provably_complete:
                    operation.status = (
                        "partial"
                        if any(result.action == "skipped_conflict" for result in operation.file_results)
                        else "completed"
                    )
                    operation.error = None
                    await self.store.update_operation(operation)
                    total += 1
                    continue
                operation.status = "failed_partial"
                operation.error = {
                    "code": "incomplete_operation",
                    "message": "恢复操作在进程退出前未完成，请先执行 operation-before 撤销",
                }
                await self.store.update_operation(operation)
                total += 1
        return total

    async def cleanup_expired(self, *, now: datetime | None = None) -> int:
        """按会话最后活动时间删除过期 checkpoint 目录。"""
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=self.retention_days)
        if not self.store.root.is_dir():
            return 0
        removed = 0
        for child in list(self.store.root.iterdir()):
            if not child.is_dir():
                continue
            index = child / "index.json"
            try:
                active_at = datetime.fromisoformat(
                    json.loads(index.read_text(encoding="utf-8")).get("last_active_at", "")
                )
            except (OSError, UnicodeDecodeError, ValueError, TypeError, AttributeError):
                # 无法证明仍有效时保守保留，不删除用户数据。
                continue
            if active_at >= cutoff:
                continue
            try:
                import shutil

                shutil.rmtree(child)
                removed += 1
            except OSError:
                continue
        return removed
