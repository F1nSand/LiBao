"""任务领域服务（《02》后端设计 §5.3 / 《02》接口契约 §5.3）。

状态机：pending / running / waiting_confirm / cancelled / done / failed。
live-tail：进程内订阅表直投（本地单机化，Redis 已删）。
I8 规则：resume 前置校验——不存在/软删→40402；status≠waiting_confirm→40902；pending_confirm 超 TTL→40902。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import get_settings
from app.core.errors import ERR_STATE_NOT_CANCELLABLE, ERR_TASK_NOT_FOUND, ERR_TASK_RUNNING, AppError
from app.services.notification import NotificationService
from app.services.serializers import serialize_task
from app.services.task_events import (
    publish_task_event,
    subscribe_task_events,
    unsubscribe_task_events,
)
from app.storage.models.task import Task
from app.storage.models.user import User
from app.storage.repositories.task import TaskRepository

logger = logging.getLogger(__name__)

TERMINAL_EVENTS = {"done", "error", "cancelled"}

_transition_locks: dict[str, asyncio.Lock] = {}
_conversation_locks: dict[str, asyncio.Lock] = {}


def _transition_lock(task_id: uuid.UUID | str) -> asyncio.Lock:
    return _transition_locks.setdefault(str(task_id), asyncio.Lock())


def _conversation_lock(conversation_id: uuid.UUID | str) -> asyncio.Lock:
    return _conversation_locks.setdefault(str(conversation_id), asyncio.Lock())


async def push_event(task_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """持久化并推送任务业务事件（旧调用方保留该名称）。"""
    await publish_task_event(task_id, event_type, payload)


async def subscribe(task_id: str) -> asyncio.Queue:
    return await subscribe_task_events(task_id)


async def unsubscribe(task_id: str, q: asyncio.Queue) -> None:
    await unsubscribe_task_events(task_id, q)


class TaskService:
    # ---- 查询 ----
    async def get_owned(self, db: Any, task_id: uuid.UUID, user_id: uuid.UUID) -> Task:
        task = await TaskRepository(db).get_by_id(task_id)
        if task is None or str(task.user_id) != str(user_id):
            raise AppError(ERR_TASK_NOT_FOUND, "任务不存在或无权访问")
        return task

    async def get_waiting_confirm_for_conversation(
        self, db: Any, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Task | None:
        return await TaskRepository(db).get_waiting_confirm_for_conversation(user_id, conversation_id)

    async def list_owned(
        self, db: Any, user_id: uuid.UUID, page: int, page_size: int, status: str | None = None
    ) -> dict[str, Any]:
        repo = TaskRepository(db)
        items = await repo.list_for_user(user_id, status=status, limit=page_size, offset=(page - 1) * page_size)
        total = await repo.count_for_user(user_id, status=status)
        from app.api.schemas.common import paged

        return paged([serialize_task(t) for t in items], total, page, page_size)

    # ---- 提交 / 状态迁移 ----
    async def submit(self, db: Any, user: User, agent_id: uuid.UUID, input: dict[str, Any]) -> Task:
        task = await TaskRepository(db).create(user_id=user.id, agent_id=agent_id, input=input, status="pending")
        await db.commit()
        await db.refresh(task)
        return task

    async def get_current_for_conversation(
        self, db: Any, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> tuple[Task | None, str | None]:
        return await TaskRepository(db).get_current_for_conversation(user_id, conversation_id)

    async def submit_for_conversation(
        self,
        db: Any,
        user: User,
        agent_id: uuid.UUID,
        conversation_id: uuid.UUID,
        input: dict[str, Any],
    ) -> Task:
        """Atomically reserve the conversation for one non-terminal task."""
        async with _conversation_lock(conversation_id):
            current, _ = await TaskRepository(db).get_current_for_conversation(user.id, conversation_id)
            if current is not None:
                raise AppError(ERR_TASK_RUNNING, "当前会话已有未完成任务，请等待其结束或先恢复/取消")
            task = await TaskRepository(db).create(
                user_id=user.id,
                agent_id=agent_id,
                conversation_id=conversation_id,
                input=input,
                status="pending",
            )
            await db.commit()
            await db.refresh(task)
            return task

    async def create_waiting_confirm(
        self,
        db: Any,
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
            conversation_id=conversation_id,
            input=input,
            status="waiting_confirm",
            pending_confirm=payload,
        )
        await db.commit()
        await db.refresh(task)
        return task

    async def set_running(self, db: Any, task: Task) -> None:
        await TaskRepository(db).update_status(task, "running", progress=0.5)
        task.started_at = task.started_at or datetime.now(UTC)
        await db.commit()
        await db.refresh(task)

    async def set_waiting_confirm(
        self,
        db: Any,
        task: Task,
        *,
        value: dict[str, Any],
        conversation_id: uuid.UUID | None,
        thread_id: str,
    ) -> None:
        """将已存在的聊天 Task 转为等待确认，保持同一 task_id 供 resume/cancel 复用。"""
        payload = dict(value)
        payload["conversation_id"] = str(conversation_id) if conversation_id else None
        payload["thread_id"] = thread_id
        payload["created_at"] = datetime.now(UTC).isoformat()
        await TaskRepository(db).set_pending_confirm(task, payload)
        await db.commit()
        await db.refresh(task)

    async def set_cancelled(self, db: Any, task: Task) -> None:
        await TaskRepository(db).update_status(task, "cancelled")
        await db.commit()
        await db.refresh(task)

    async def set_done(
        self, db: Any, task: Task, final_message: dict[str, Any], *, _lock_held: bool = False
    ) -> None:
        async def _write() -> None:
            if task.status == "cancelled":
                return
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

        if _lock_held:
            await _write()
        else:
            async with _transition_lock(task.id):
                await _write()

    async def set_failed(
        self, db: Any, task: Task, message: str | dict[str, Any], *, _lock_held: bool = False
    ) -> None:
        if isinstance(message, dict):
            error_payload = dict(message)
            notification_message = str(error_payload.get("message") or "任务执行失败")
        else:
            error_payload = {"code": "task_error", "message": message, "retryable": False, "recoverable": False}
            notification_message = message

        async def _write() -> None:
            if task.status == "cancelled":
                return
            await TaskRepository(db).update_finish(
                task,
                status="failed",
                error=error_payload,
            )
            await db.commit()
            await db.refresh(task)
            # 2d：任务失败通知（任务事件产生源）
            if task.user_id is not None:
                await NotificationService().create(
                    db, user_id=task.user_id, title="任务执行失败", level="error", body=notification_message[:200]
                )

        if _lock_held:
            await _write()
        else:
            async with _transition_lock(task.id):
                await _write()

    # ---- 取消 / 恢复 ----
    async def cancel(self, db: Any, task: Task) -> None:
        async with _transition_lock(task.id):
            current = await TaskRepository(db).get_by_id(task.id)
            if current is None or current.status in ("done", "cancelled"):
                raise AppError(ERR_STATE_NOT_CANCELLABLE, "任务已完成或已取消，不可再取消")
            await self.set_cancelled(db, current)
            await push_event(str(current.id), "cancelled", {"status": "cancelled"})

    @staticmethod
    def resolve_resume_thread(task: Task) -> str:
        """恢复目标线程（单一解析点）：pending_confirm.thread_id → conversation_id → task.id。

        chat/invoke 来源的中断任务 thread 是 conversation.id/uuid4（写在 pending_confirm）；
        后台任务（POST /tasks）无 pending_confirm 时 thread 即 task.id。
        """
        pending = task.pending_confirm or {}
        return str(pending.get("thread_id") or pending.get("conversation_id") or task.id)

    @staticmethod
    def resolve_execution_thread(task: Task) -> str:
        """恢复普通 chat failed Task 时也命中 conversation thread；确认任务保持旧优先级。"""
        pending = task.pending_confirm or {}
        task_input = task.input if isinstance(task.input, dict) else {}
        return str(
            pending.get("thread_id")
            or getattr(task, "conversation_id", None)
            or task_input.get("conversation_id")
            or task.id
        )

    async def recover_precheck(self, db: Any, task: Task, idempotency_key: str) -> str:
        """CAS failed→running；重复 key 在已有运行中时不重复启动 producer。"""
        async with _transition_lock(task.id):
            current = await TaskRepository(db).get_by_id(task.id)
            if current is None:
                raise AppError(ERR_TASK_NOT_FOUND, "任务不存在")
            if current.status == "running" and current.recovery_key == idempotency_key:
                return "already_running"
            error = current.error if isinstance(current.error, dict) else {}
            if current.status != "failed" or not error.get("recoverable"):
                raise AppError(ERR_STATE_NOT_CANCELLABLE, "任务当前不可从断点恢复")
            if int(getattr(current, "recovery_attempts", 0) or 0) >= 3:
                raise AppError(ERR_STATE_NOT_CANCELLABLE, "断点恢复次数已达上限")
            current.recovery_attempts = int(getattr(current, "recovery_attempts", 0) or 0) + 1
            current.recovery_key = idempotency_key
            current.status = "running"
            current.progress = 0.5
            current.finished_at = None
            await db.commit()
            await db.refresh(current)
            return "start"

    async def resume_precheck(self, db: Any, task: Task) -> None:
        """I8 前置校验（《02》后端设计 §3.4）：状态必须 waiting_confirm 且载荷未超 TTL。"""
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
