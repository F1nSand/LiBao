"""Startup reconciliation for tasks whose in-process runner disappeared.

The backend deliberately does not auto-replay work after a process restart.  A
running task is converted to a recoverable ``process_restart`` failure only
when an exact LangGraph checkpoint can be verified; otherwise it is marked
non-recoverable and the user must submit the work again.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.errors import ERR_TASK_PROCESS_INTERRUPTED
from app.services.serializers import serialize_message
from app.services.task_events import list_task_events, publish_task_event
from app.storage.file.store import get_store
from app.storage.models.message import Message
from app.storage.models.task import Task
from app.storage.repositories.message import MessageRepository
from app.storage.repositories.task import TaskRepository

logger = logging.getLogger(__name__)

PROCESS_RESTART_KIND = "process_restart"


def _conversation_id(task: Task) -> uuid.UUID | None:
    """Resolve a conversation binding from new and legacy task rows."""
    raw = getattr(task, "conversation_id", None)
    if raw is None:
        task_input = task.input if isinstance(task.input, dict) else {}
        pending = task.pending_confirm if isinstance(task.pending_confirm, dict) else {}
        raw = task_input.get("conversation_id") or pending.get("conversation_id")
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (AttributeError, ValueError):
        return None


async def _verified_cursor(task: Task, graph: Any) -> str | None:
    """Resolve and re-read one exact graph checkpoint for a task.

    Chat tasks use the code checkpoint's run bounds.  Background tasks use the
    task id as their graph thread and first discover its persisted latest tuple.
    Every discovered id is then passed back explicitly to ``aget_tuple`` so a
    thread-level ``__error__`` resolver can never silently select another run.
    """
    checkpointer = getattr(graph, "checkpointer", None)
    resolver = getattr(checkpointer, "aget_tuple", None)
    if checkpointer is None or resolver is None:
        return None

    conversation_id = _conversation_id(task)
    if conversation_id is not None:
        task_input = task.input if isinstance(task.input, dict) else {}
        code_checkpoint_id = task_input.get("checkpoint_id")
        if not code_checkpoint_id:
            return None
        run_bounds = getattr(checkpointer, "aget_run_bounds", None)
        if run_bounds is None:
            return None
        try:
            _, output_id, _ = await run_bounds(
                {"configurable": {"thread_id": str(conversation_id)}}, str(code_checkpoint_id)
            )
        except Exception:  # noqa: BLE001 - a corrupt checkpoint must fail closed
            logger.warning("unable to resolve chat task cursor %s", task.id, exc_info=True)
            return None
        if output_id is None:
            return None
        expected = str(output_id)
        try:
            checkpoint_tuple = await resolver(
                {"configurable": {"thread_id": str(conversation_id), "checkpoint_id": expected}}
            )
        except Exception:  # noqa: BLE001 - checkpoint validation is best effort
            logger.warning("unable to validate chat task cursor %s", task.id, exc_info=True)
            return None
        return expected if _tuple_matches(checkpoint_tuple, expected) else None

    thread_id = str(task.id)
    try:
        latest = await resolver({"configurable": {"thread_id": thread_id}})
    except Exception:  # noqa: BLE001
        logger.warning("unable to read background task cursor %s", task.id, exc_info=True)
        return None
    discovered = _tuple_checkpoint_id(latest)
    if discovered is None:
        return None
    try:
        exact = await resolver({"configurable": {"thread_id": thread_id, "checkpoint_id": discovered}})
    except Exception:  # noqa: BLE001
        logger.warning("unable to validate background task cursor %s", task.id, exc_info=True)
        return None
    return discovered if _tuple_matches(exact, discovered) else None


def _tuple_checkpoint_id(checkpoint_tuple: Any) -> str | None:
    if checkpoint_tuple is None:
        return None
    config = getattr(checkpoint_tuple, "config", None) or {}
    configurable = config.get("configurable", config) if isinstance(config, dict) else {}
    checkpoint_id = configurable.get("checkpoint_id") if isinstance(configurable, dict) else None
    if checkpoint_id is None:
        checkpoint = getattr(checkpoint_tuple, "checkpoint", None) or {}
        if isinstance(checkpoint, dict):
            checkpoint_id = checkpoint.get("id")
    return str(checkpoint_id) if checkpoint_id is not None else None


def _tuple_matches(checkpoint_tuple: Any, expected: str) -> bool:
    """Accept real LangGraph tuples and small test doubles with an id-bearing config."""
    if checkpoint_tuple is None:
        return False
    actual = _tuple_checkpoint_id(checkpoint_tuple)
    # Some third-party checkpointers omit the id from the returned config while
    # still honoring an explicit lookup.  Presence of a tuple is sufficient in
    # that case; JsonFileSaver always exposes the id and takes the strict path.
    return actual is None or actual == expected


async def _persisted_assistant(task: Task) -> Message | None:
    """Detect the crash window after assistant Message commit but before Task.done."""
    conversation_id = _conversation_id(task)
    if conversation_id is None:
        return None
    try:
        records = await list_task_events(str(task.id), after_seq=0)
    except Exception:  # noqa: BLE001
        return None
    message_repo = MessageRepository()
    for record in records:
        if record.get("type") != "message_start":
            continue
        payload = record.get("payload") or {}
        raw_id = payload.get("message_id")
        if not raw_id:
            continue
        try:
            message_id = uuid.UUID(str(raw_id))
        except (AttributeError, ValueError):
            continue
        message = await message_repo.get_in_conversation(conversation_id, message_id)
        if message is not None and message.role == "assistant":
            return message
    return None


def _restart_error(*, recoverable: bool, reason: str) -> dict[str, Any]:
    return {
        "code": ERR_TASK_PROCESS_INTERRUPTED,
        "message": (
            "服务进程重启导致任务中断，可从断点继续"
            if recoverable
            else "服务进程重启导致任务中断，未找到可验证断点，请重新提交"
        ),
        "kind": PROCESS_RESTART_KIND,
        "retryable": bool(recoverable),
        "recoverable": bool(recoverable),
        "details": {"reason": reason},
    }


async def _mark_reconciled(db: Any, task: Task, *, cursor: str | None, reason: str) -> None:
    task.recovery_graph_checkpoint_id = cursor
    error = _restart_error(recoverable=cursor is not None, reason=reason)
    task.status = "failed"
    task.error = error
    task.finished_at = datetime.now(UTC)
    await db.commit()
    await publish_task_event(
        str(task.id),
        "error",
        {
            **error,
            "task_id": str(task.id),
        },
    )


async def reconcile_orphaned_tasks(graph: Any) -> dict[str, int]:
    """Reconcile pending/running rows once during startup; never auto-spawn work."""
    store = get_store()
    if store is None:
        return {"scanned": 0, "recovered": 0, "nonrecoverable": 0, "completed": 0}
    stats = {"scanned": 0, "recovered": 0, "nonrecoverable": 0, "completed": 0}
    async with store.session() as db:
        tasks = await TaskRepository(db).list_all(statuses={"pending", "running"})
        for task in tasks:
            stats["scanned"] += 1
            # A final assistant may have been committed immediately before the
            # process died; preserve that result instead of asking the user to
            # retry and potentially duplicating an external side effect.
            assistant = await _persisted_assistant(task)
            if assistant is not None:
                task.status = "done"
                task.output = serialize_message(assistant)
                task.finished_at = datetime.now(UTC)
                await db.commit()
                await publish_task_event(
                    str(task.id),
                    "done",
                    {"message_id": str(assistant.id), "message": serialize_message(assistant)},
                )
                stats["completed"] += 1
                continue
            cursor = await _verified_cursor(task, graph) if task.status == "running" else None
            await _mark_reconciled(
                db,
                task,
                cursor=cursor,
                reason="verified_graph_cursor" if cursor is not None else "no_verified_graph_cursor",
            )
            if cursor is not None:
                stats["recovered"] += 1
            else:
                stats["nonrecoverable"] += 1
    return stats
