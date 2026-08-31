"""任务路由（《02》接口契约 §5.3）。提交/列表/详情/取消/resume（双轨）/events（回放+live-tail）。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.api.schemas.tasks import SubmitTaskRequest, TaskRecoverRequest, TaskResumeRequest
from app.core.errors import ERR_CHECKPOINT_INVALID, ERR_TASK_NOT_FOUND, AppError
from app.core.events import format_sse, make_event
from app.core.logging import get_trace_id
from app.orchestration.chat_stream import resume_stream_events, retry_stream_events
from app.orchestration.checkpoint_codec import CheckpointDecodeError
from app.orchestration.task_worker import route_cancel, spawn_recovery, spawn_run
from app.services.agent import AgentService
from app.services.attachment import AttachmentService
from app.services.serializers import serialize_task
from app.services.task import TaskService, subscribe, unsubscribe
from app.services.task_events import list_task_events
from app.storage.models.task import Task
from app.storage.models.user import User

router = APIRouter()


async def _task_event_stream(db: Any, task: Task, after_seq: int = 0) -> AsyncIterator[str]:
    """持久业务事件回放 → live-tail；task_seq 跨连接单调，连接 seq 仅供本次 SSE。"""
    stream_seq = 0

    def emit_record(event_type: str, payload: dict[str, Any], task_seq: int | None = None) -> str:
        nonlocal stream_seq
        stream_seq += 1
        return format_sse(make_event(event_type, payload, stream_seq, task_seq=task_seq))

    # 先订阅再读历史，读/订阅之间发布的事件会通过 task_seq 去重。
    q = await subscribe(str(task.id))
    try:
        cursor = after_seq
        records = await list_task_events(str(task.id), after_seq=after_seq)
        for record in records:
            seq = int(record.get("task_seq", 0))
            if seq <= cursor:
                continue
            yield emit_record(str(record.get("type") or "status"), record.get("payload") or {}, seq)
            cursor = seq

        # 兼容尚无 JSONL 事件的旧任务，首次连接仍返回一次状态快照。
        if not records and after_seq == 0:
            if task.status == "waiting_confirm" and task.pending_confirm:
                pc = task.pending_confirm
                yield emit_record(
                    "interrupt",
                    {"node_id": pc.get("node_id"), "payload": pc, "confirm_required": True, "task_id": str(task.id)},
                )
            elif task.status == "done":
                yield emit_record(
                    "done",
                    {
                        "message_id": None,
                        "token_usage": (task.output or {}).get("token_usage"),
                        "cost": None,
                        "message": task.output,
                    },
                )
            elif task.status == "failed":
                error = task.error or {}
                yield emit_record(
                    "error",
                    {
                        "code": error.get("code", 50001),
                        "message": error.get("message", "任务执行失败"),
                        "kind": error.get("kind"),
                        "retryable": error.get("retryable", False),
                        "recoverable": error.get("recoverable", False),
                        "details": error.get("details"),
                    },
                )
            elif task.status == "cancelled":
                yield emit_record("status", {"status": "cancelled", "context_metrics": None})
            else:
                yield emit_record("status", {"status": task.status, "context_metrics": {"progress": task.progress}})
        if task.status in ("done", "failed", "cancelled"):
            return
        while True:
            item = await q.get()
            if item is None:
                break
            event_type, payload, task_seq = item
            if int(task_seq) <= cursor:
                continue
            cursor = int(task_seq)
            yield emit_record(event_type, payload, cursor)
    finally:
        await unsubscribe(str(task.id), q)


@router.post("/tasks")
async def submit_task(
    req: SubmitTaskRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    agent = await AgentService().get_default(db, user.org_id)  # 单通用 Agent，不接收 agent_id
    attachment_ids = req.input.get("attachment_ids", [])
    if attachment_ids:
        await AttachmentService().get_owned_many(db, user.id, [uuid.UUID(value) for value in attachment_ids])
    task = await TaskService().submit(db, user, agent.id, req.input)
    # 本地单机化：直接进程内跑图（spawn_run 注册进 _RUNNING，可取消）
    spawn_run(
        graph=request.app.state.graph,
        task_id=task.id,
        trace_id=get_trace_id(),
    )
    return ok({"task_id": str(task.id)})


@router.get("/tasks")
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    data = await TaskService().list_owned(db, user.id, page, page_size, status=status)
    return ok(data)


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    task = await TaskService().get_owned(db, task_id, user.id)
    return ok(serialize_task(task))


@router.get("/tasks/{task_id}/events")
async def task_events(
    task_id: uuid.UUID,
    request: Request,
    after_seq: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    task = await TaskService().get_owned(db, task_id, user.id)
    if after_seq == 0:
        last_event_id = request.headers.get("last-event-id", "")
        cursor_text = last_event_id.rsplit(":", 1)[-1]
        if cursor_text.startswith("task_evt_"):
            cursor_text = cursor_text.removeprefix("task_evt_")
        try:
            after_seq = max(0, int(cursor_text))
        except ValueError:
            pass
    return StreamingResponse(
        _task_event_stream(db, task, after_seq=after_seq),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    task = await TaskService().get_owned(db, task_id, user.id)
    await TaskService().cancel(db, task)
    # M6-3：跨实例 cancel 路由（本地 fut.cancel 降级 + 查 claim 向持有实例广播）
    await route_cancel(str(task.id))
    return ok()


@router.post("/tasks/{task_id}/recover")
async def recover_task(
    task_id: uuid.UUID,
    req: TaskRecoverRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    """从可恢复的模型传输失败 checkpoint 继续；不重新提交原用户消息。"""
    service = TaskService()
    task = await service.get_owned(db, task_id, user.id)
    decision = await service.recover_precheck(db, task, req.idempotency_key)
    if decision == "already_running":
        return ok({"task_id": str(task.id), "status": "running"})
    trace_id = get_trace_id()
    graph = request.app.state.graph
    if "text/event-stream" in request.headers.get("accept", "") and (task.input or {}).get("conversation_id"):
        return StreamingResponse(
            retry_stream_events(
                db=db,
                graph=graph,
                task=task,
                user=user,
                trace_id=trace_id,
            ),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    spawn_recovery(graph=graph, task_id=task.id, trace_id=trace_id)
    return ok({"task_id": str(task.id), "status": "running"})


@router.post("/tasks/{task_id}/resume")
async def resume_task(
    task_id: uuid.UUID,
    req: TaskResumeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    task = await TaskService().get_owned(db, task_id, user.id)
    await TaskService().resume_precheck(db, task)
    approved = bool((req.confirm or {}).get("approved"))

    # I8：thread 有效性校验（无效 → 40402，《02》后端设计 §3.4）
    graph = request.app.state.graph
    thread_id = TaskService.resolve_resume_thread(task)
    try:
        snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    except CheckpointDecodeError as exc:
        raise AppError(ERR_CHECKPOINT_INVALID, "任务检查点无法读取，任务仍保持等待确认", retryable=False) from exc
    if not snapshot.values and not snapshot.next:
        raise AppError(ERR_TASK_NOT_FOUND, "任务线程已失效，无法恢复")

    trace_id = get_trace_id()
    if "text/event-stream" in request.headers.get("accept", ""):
        # SSE 轨：续流（chat 弹窗 / 任务详情流式）
        return StreamingResponse(
            resume_stream_events(db=db, graph=graph, task=task, user=user, approved=approved, trace_id=trace_id),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )
    # JSON 轨：后台续跑（TaskDetail 非流式）；进程内 spawn_run（注册进 _RUNNING 可取消）
    spawn_run(
        graph=graph,
        task_id=task.id,
        approved=approved,
        trace_id=trace_id,
    )
    return ok()
