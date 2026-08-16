"""任务领域服务（docs 01 §5.3 / docs 03 §5.3）。

状态机：pending / running / waiting_confirm / cancelled / done / failed。
live-tail：进程内事件订阅表（单进程接缝，多实例为 M4 Redis 广播）。
I8 规则：resume 前置校验——不存在/软删→40402；status≠waiting_confirm→40902；pending_confirm 超 TTL→40902。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ERR_STATE_NOT_CANCELLABLE, ERR_TASK_NOT_FOUND, AppError
from app.services.notification import NotificationService
from app.services.serializers import serialize_task
from app.storage.models.task import Task
from app.storage.models.user import User
from app.storage.repositories.task import TaskRepository

# ---- live-tail（进程内）----
_tails: dict[str, list[asyncio.Queue]] = {}


def push_event(task_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """推事件给所有订阅者；终态（done/error/cancelled）后推 None 哨兵关闭。"""
    queues = _tails.get(task_id)
    if queues:
        for q in queues:
            q.put_nowait((event_type, payload))
    if event_type in ("done", "error", "cancelled"):
        for q in queues or []:
            q.put_nowait(None)
        _tails.pop(task_id, None)


def subscribe(task_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _tails.setdefault(task_id, []).append(q)
    return q


def unsubscribe(task_id: str, q: asyncio.Queue) -> None:
    queues = _tails.get(task_id)
    if queues and q in queues:
        queues.remove(q)
        if not queues:
            _tails.pop(task_id, None)


class TaskService:
    # ---- 查询 ----
    async def get_owned(self, db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> Task:
        task = await TaskRepository(db).get_by_id(task_id)
        if task is None or str(task.user_id) != str(user_id):
            raise AppError(ERR_TASK_NOT_FOUND, "任务不存在或无权访问")
        return task

    async def list_owned(
        self, db: AsyncSession, user_id: uuid.UUID, page: int, page_size: int, status: str | None = None
    ) -> dict[str, Any]:
        repo = TaskRepository(db)
        items = await repo.list_for_user(user_id, status=status, limit=page_size, offset=(page - 1) * page_size)
        total = await repo.count_for_user(user_id, status=status)
        from app.api.schemas.common import paged

        return paged([serialize_task(t) for t in items], total, page, page_size)

    # ---- 提交 / 状态迁移 ----
    async def submit(self, db: AsyncSession, user: User, agent_id: uuid.UUID, input: dict[str, Any]) -> Task:
        task = await TaskRepository(db).create(user_id=user.id, agent_id=agent_id, input=input, status="pending")
        await db.commit()
        await db.refresh(task)
        return task

    async def create_waiting_confirm(
        self,
        db: AsyncSession,
        *,
        user: User,
        agent_id: uuid.UUID,
        input: dict[str, Any],
        value: dict[str, Any],
        conversation_id: uuid.UUID | None = None,
        thread_id: str,
    ) -> Task:
        """interrupt 载荷落 Task 行（pending_confirm 含 thread 信息，Task 表无 conversation_id 列）。"""
        payload = dict(value)
        payload["conversation_id"] = str(conversation_id) if conversation_id else None
        payload["thread_id"] = thread_id
        payload["created_at"] = datetime.now(UTC).isoformat()
        task = await TaskRepository(db).create(
            user_id=user.id,
            agent_id=agent_id,
            input=input,
            status="waiting_confirm",
            pending_confirm=payload,
        )
        await db.commit()
        await db.refresh(task)
        return task

    async def set_running(self, db: AsyncSession, task: Task) -> None:
        await TaskRepository(db).update_status(task, "running", progress=0.5)
        task.started_at = task.started_at or datetime.now(UTC)
        await db.commit()
        await db.refresh(task)

    async def set_cancelled(self, db: AsyncSession, task: Task) -> None:
        await TaskRepository(db).update_status(task, "cancelled")
        await db.commit()
        await db.refresh(task)

    async def set_done(self, db: AsyncSession, task: Task, final_message: dict[str, Any]) -> None:
        await TaskRepository(db).update_finish(task, status="done", output=final_message)
        await db.commit()
        await db.refresh(task)
        # 2d：任务完成通知（任务事件产生源）
        if task.user_id is not None:
            await NotificationService().create(
                db,
                user_id=task.user_id,
                title="任务已完成",
                level="success",
                body=str((final_message or {}).get("content", ""))[:200] or None,
            )

    async def set_failed(self, db: AsyncSession, task: Task, message: str) -> None:
        await TaskRepository(db).update_finish(task, status="failed", error={"code": "task_error", "message": message})
        await db.commit()
        await db.refresh(task)
        # 2d：任务失败通知（任务事件产生源）
        if task.user_id is not None:
            await NotificationService().create(
                db, user_id=task.user_id, title="任务执行失败", level="error", body=message[:200]
            )

    # ---- 取消 / 恢复 ----
    async def cancel(self, db: AsyncSession, task: Task) -> None:
        if task.status in ("done", "cancelled"):
            raise AppError(ERR_STATE_NOT_CANCELLABLE, "任务已完成或已取消，不可再取消")
        await self.set_cancelled(db, task)
        push_event(str(task.id), "cancelled", {"status": "cancelled"})

    @staticmethod
    def resolve_resume_thread(task: Task) -> str:
        """恢复目标线程（单一解析点）：pending_confirm.thread_id → conversation_id → task.id。

        chat/invoke 来源的中断任务 thread 是 conversation.id/uuid4（写在 pending_confirm）；
        后台任务（POST /tasks）无 pending_confirm 时 thread 即 task.id。
        """
        pending = task.pending_confirm or {}
        return str(pending.get("thread_id") or pending.get("conversation_id") or task.id)

    async def resume_precheck(self, db: AsyncSession, task: Task) -> None:
        """I8 前置校验（docs 01 §3.4）：状态必须 waiting_confirm 且载荷未超 TTL。"""
        if task.status != "waiting_confirm":
            raise AppError(ERR_STATE_NOT_CANCELLABLE, "任务状态不允许恢复（非等待确认中）")
        pending = task.pending_confirm or {}
        created_raw = pending.get("created_at")
        if not created_raw:
            raise AppError(ERR_STATE_NOT_CANCELLABLE, "缺少确认载荷，无法恢复")
        created = datetime.fromisoformat(created_raw)
        ttl = timedelta(hours=get_settings().task_confirm_ttl_hours)
        if datetime.now(UTC) - created > ttl:
            raise AppError(ERR_STATE_NOT_CANCELLABLE, "确认载荷已过期，请重新发起确认")
