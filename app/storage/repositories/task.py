"""任务数据访问（docs 04 §3.3）。status 状态机：pending/running/waiting_confirm/cancelled/done/failed。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.task import Task


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
        self.session.add(task)
        return task

    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        stmt = select(Task).where(Task.id == task_id, Task.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        stmt = select(Task).where(Task.user_id == user_id, Task.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Task.status == status)
        stmt = stmt.order_by(Task.created_at.desc()).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars())

    async def count_for_user(self, user_id: uuid.UUID, *, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(Task).where(Task.user_id == user_id, Task.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Task.status == status)
        return int((await self.session.execute(stmt)).scalar_one())

    async def update_status(self, task: Task, status: str, *, progress: float | None = None) -> None:
        task.status = status
        if progress is not None:
            task.progress = progress
        self.session.add(task)

    async def set_pending_confirm(self, task: Task, value: dict[str, Any]) -> None:
        task.pending_confirm = value
        task.status = "waiting_confirm"
        task.progress = 0.5
        self.session.add(task)

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
        self.session.add(task)
