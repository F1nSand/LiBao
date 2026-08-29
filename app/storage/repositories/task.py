"""任务数据访问（docs 04 §3.3）。status 状态机：pending/running/waiting_confirm/cancelled/done/failed。

文件化：.agent/tasks.json（FileTable，内存过滤/排序/分页；字段赋值经 Row 标脏，commit 落盘）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.storage.file.store import get_store
from app.storage.models.task import Task


class TaskRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.table = get_store().table("tasks")

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        agent_id: uuid.UUID,
        input: dict[str, Any],
        status: str = "pending",
        pending_confirm: dict[str, Any] | None = None,
    ) -> Task:
        task = Task(
            user_id=user_id,
            agent_id=agent_id,
            input=input,
            status=status,
            pending_confirm=pending_confirm,
            progress=0.0,
        )
        self.table.register(task)
        return task

    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        row = await self.table.get(task_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        return await self.table.list(
            filter_fn=lambda t: (
                t.user_id == user_id and t.deleted_at is None and (status is None or t.status == status)
            ),
            sort_key=lambda t: t.created_at,
            desc=True,
            limit=limit,
            offset=offset,
        )

    async def count_for_user(self, user_id: uuid.UUID, *, status: str | None = None) -> int:
        return await self.table.count(
            filter_fn=lambda t: (
                t.user_id == user_id and t.deleted_at is None and (status is None or t.status == status)
            )
        )

    async def get_waiting_confirm_for_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Task | None:
        items = await self.table.list(
            filter_fn=lambda t: (
                t.user_id == user_id
                and t.deleted_at is None
                and t.status == "waiting_confirm"
                and str((t.pending_confirm or {}).get("conversation_id") or "") == str(conversation_id)
            ),
            sort_key=lambda t: t.created_at,
            desc=True,
            limit=1,
        )
        return items[0] if items else None

    async def update_status(self, task: Task, status: str, *, progress: float | None = None) -> None:
        task.status = status
        if progress is not None:
            task.progress = progress

    async def set_pending_confirm(self, task: Task, value: dict[str, Any]) -> None:
        task.pending_confirm = value
        task.status = "waiting_confirm"
        task.progress = 0.5

    async def update_finish(
        self, task: Task, *, status: str, output: dict[str, Any] | None = None, error: dict[str, Any] | None = None
    ) -> None:
        task.status = status
        task.progress = 1.0 if status == "done" else task.progress
        task.finished_at = datetime.now(UTC)
        if output is not None:
            task.output = output
        if error is not None:
            task.error = error
