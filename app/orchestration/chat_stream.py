"""Graph→SSE 桥（docs 03 §3.3，M1 核心 + M2 interrupt/resume）。

职责（docs 01 §5.2）：graph.astream → SSE 事件信封（共享循环在 stream_core.py）；
消息持久化在此（节点保持无 DB）：开头落用户消息，流结束落 assistant 最终消息 + run_logs + last_message_at。
M2：require_confirm 工具 → interrupt 事件（自动建 Task 承接）→ POST /tasks/{id}/resume → resume_stream_events 续流。
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langgraph.types import Command

from app.checkpoints.identity import build_workspace_identity
from app.checkpoints.runtime import get_checkpoint_service
from app.core.config import get_settings
from app.core.events import sse_emitter
from app.orchestration.document_context import (
    PreparedDocumentContext,
    prepare_document_context,
    prepare_resume_document_context,
)
from app.orchestration.multimodal_input import PreparedImageInput, image_config, prepare_image_input
from app.orchestration.stream_core import build_initial_state, stream_graph_events
from app.services.notification import maybe_notify_from_tool_results
from app.services.serializers import serialize_message
from app.services.task import TaskService, push_event
from app.services.tool import ToolService
from app.storage.models.agent import AgentConfig
from app.storage.models.conversation import Conversation
from app.storage.models.message import Message
from app.storage.models.task import Task
from app.storage.models.user import User
from app.storage.repositories.agent import AgentRepository
from app.storage.repositories.attachment import AttachmentRepository
from app.storage.repositories.conversation import ConversationRepository
from app.storage.repositories.message import MessageRepository
from app.storage.repositories.run_log import RunLogRepository
from app.storage.repositories.task import TaskRepository


async def _backfill_attachments(
    db: Any, attachment_ids: list[str], conversation_id: uuid.UUID, message_id: uuid.UUID
) -> None:
    """附件回填 conversation_id/message_id（消息回放时附件可解析归属）。文件化：逐行回填。"""
    from app.storage.repositories.attachment import AttachmentRepository

    repo = AttachmentRepository(db)
    for aid in attachment_ids:
        await repo.backfill_conversation(uuid.UUID(aid), conversation_id, message_id)

def _spawn_memory_extract(
    final_state: dict[str, Any],
    user: User,
    trace_id: str,
    session_id: uuid.UUID | None,
    workspace: dict[str, Any] | None,
) -> None:
    """流结束后台触发主动记忆提取（best-effort：失败/禁用静默，不阻塞调用方）。"""
    from app.services.memory_extract import extract_and_store, spawn_extract

    if not workspace:
        workspace = {}
    spawn_extract(
        extract_and_store(
            messages=final_state.get("messages", []),
            user_id=str(user.id),
            workspace_id=workspace.get("id"),
            workspace_root=workspace.get("root_path"),
            trace_id=trace_id,
            session_id=session_id,
        )
    )


def _title_from(content: str, max_chars: int = 20) -> str:
    """会话标题生成：首条消息前 max_chars 字（超长加省略号，与前端 truncate 同语义）。"""
    text = content.strip()
    return f"{text[:max_chars]}…" if len(text) > max_chars else text


def _graph_config(
    *,
    thread_id: str,
    trace_id: str,
    assistant_msg_id: uuid.UUID,
    model_override: Any = None,
    image_payload: dict[str, Any] | None = None,
    current_image_ids: set[str] | None = None,
    vision: bool = False,
    image_context: PreparedImageInput | None = None,
    force_image_context: bool = False,
    document_context: PreparedDocumentContext | None = None,
    checkpoint_id: uuid.UUID | None = None,
    graph_parent_checkpoint_id: str | None = None,
    start_graph_from_root: bool = False,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "trace_id": trace_id,
            "assistant_msg_id": str(assistant_msg_id),
        }
    }
    if checkpoint_id is not None:
        cfg["configurable"]["code_checkpoint_id"] = str(checkpoint_id)
    if graph_parent_checkpoint_id is not None:
        cfg["configurable"]["checkpoint_id"] = str(graph_parent_checkpoint_id)
    elif start_graph_from_root:
        cfg["configurable"]["start_graph_from_root"] = True
    if model_override is not None:
        cfg["configurable"]["model"] = model_override
    # 多模态：图片 b64 载荷只进 configurable（不落 checkpoint）。新路径使用共享准备结果；
    # 保留旧参数以兼容测试和少量内部调用。
    if force_image_context:
        cfg["configurable"].update(image_config(image_context, force_context=True))
    elif image_context is not None:
        # chat 每轮都显式建立上下文；空附件轮也必须触发历史 image_ref 净化。
        cfg["configurable"].update(image_config(image_context, force_context=True))
    elif image_payload:
        cfg["configurable"]["image_payload"] = image_payload
        cfg["configurable"]["current_image_ids"] = set(current_image_ids or [])
        cfg["configurable"]["vision"] = vision
    if document_context is not None:
        # 文档正文只存在于本次运行的 configurable；state/checkpoint 仅保存 refs。
        cfg["configurable"]["document_context"] = {
            "index": document_context.index,
            "current_ids": set(document_context.index),
        }
    return cfg


def _done_payload(assistant_msg_id: uuid.UUID, totals: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": str(assistant_msg_id),
        "token_usage": totals,
        "cost": totals.get("cost"),
        "message": message,
    }


async def chat_stream_events(
    *,
    db: Any,
    graph: Any,
    conversation: Conversation,
    agent: AgentConfig,
    user: User,
    content: str,
    attachments: list[str] | None = None,
    file_refs: list[str] | None = None,
    workspace: dict[str, Any] | None = None,
    trace_id: str,
    task: Task | None = None,
    model_override: Any = None,
    attachment_mimes: dict[str, str] | None = None,
) -> AsyncIterator[str]:
    emit = sse_emitter()
    msg_repo = MessageRepository(db)
    # 逐轮消息收集（docs 03 §3 多消息扩展）：stream_core 每轮工具结果齐后 append + 即时落库
    round_sink: list[dict[str, Any]] = []

    async def _task_cancelled() -> bool:
        """在 graph 启动前观察持久化状态，收口首帧前的取消竞态。"""
        if task is None:
            return False
        current = await TaskRepository(db).get_by_id(task.id)
        return current is None or current.status == "cancelled"

    async def _clear_prestart_cancel() -> None:
        if task is not None:
            from app.orchestration.task_worker import clear_cancel_requested

            clear_cancel_requested(str(task.id))

    if await _task_cancelled():
        await _clear_prestart_cancel()
        return

    # ---- ⓪ 多模态图片载荷准备（不进 state/checkpoint）----
    # owner 校验、mime 过滤、vision 判定、读盘和预算都由共享流水线收口。
    from app.orchestration.stream_core import resolve_effective_model

    prepared_images = await prepare_image_input(
        db,
        user_id=user.id,
        attachment_ids=list(attachments or []),
        effective_model=resolve_effective_model(agent),
    )
    prepared_documents = await prepare_document_context(
        db,
        user_id=user.id,
        user_content=content,
        attachment_ids=list(attachments or []),
        file_refs=list(file_refs or []),
        workspace=workspace,
    )
    if await _task_cancelled():
        await _clear_prestart_cancel()
        return

    checkpoint_service = get_checkpoint_service(
        get_settings().agent_data_dir, get_settings().checkpoint_retention_days
    )
    user_message_id = uuid.uuid4()
    checkpoint_id = uuid.uuid4()
    graph_parent_checkpoint_id: str | None = None
    graph_parent_bound = False
    start_graph_from_root = False
    graph_checkpointer = getattr(graph, "checkpointer", None)
    if conversation.graph_cursor_initialized:
        graph_parent_checkpoint_id = conversation.active_graph_checkpoint_id
        graph_parent_bound = True
        start_graph_from_root = graph_parent_checkpoint_id is None
    else:
        graph_tuple_resolver = getattr(graph_checkpointer, "aget_tuple", None)
        if graph_tuple_resolver is not None:
            graph_tuple = await graph_tuple_resolver(
                {"configurable": {"thread_id": str(conversation.id)}}
            )
            if graph_tuple is not None:
                graph_parent_checkpoint_id = str(
                    (graph_tuple.config.get("configurable") or {}).get("checkpoint_id")
                    or graph_tuple.checkpoint.get("id")
                )
                graph_parent_bound = True
        elif conversation.history_revision == 0:
            # A brand-new conversation without a compiled checkpointer is an explicit graph root.
            graph_parent_bound = True
    previous_head = conversation.active_message_head_id
    if previous_head is None:
        existing_messages = await msg_repo.list_by_conversation(conversation.id, limit=None, offset=0)
        previous_head = existing_messages[-1].id if existing_messages else None
    if workspace:
        workspace_root = workspace["root_path"]
        workspace_id = workspace.get("id")
    else:
        # Direct callers (tests and recovery integrations) may omit the router's
        # implicit session workspace; use the same isolated cache root here.
        workspace_root = str(Path(get_settings().cache_dir) / "sessions" / str(conversation.id))
        Path(workspace_root).mkdir(parents=True, exist_ok=True)
        workspace_id = None
    workspace_identity = build_workspace_identity(workspace_root, workspace_id)
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation.id,
        user_message_id=user_message_id,
        workspace_identity=workspace_identity,
        anchor_message_head_id=previous_head,
        checkpoint_id=checkpoint_id,
        graph_parent_checkpoint_id=graph_parent_checkpoint_id,
        graph_parent_bound=graph_parent_bound,
    )

    async def _persist_round(round_msg: dict[str, Any]) -> None:
        """即时落库（docs 03 §3）：每轮工具结果齐后同步写该轮 Message（任务中 DB 已有已完成轮次）。"""
        row = await msg_repo.create(
            conversation_id=conversation.id,
            role="assistant",
            content=round_msg["content"],
            thinking=round_msg.get("thinking") or "",
            tool_calls=round_msg["tool_calls"],
            token_usage=round_msg.get("token_usage"),
            parent_id=user_msg.id,
            history_parent_id=conversation.active_message_head_id,
            trace_id=trace_id,
            round=round_msg["round"],
            message_id=uuid.UUID(round_msg["id"]),
        )
        conversation.active_message_head_id = row.id
        conversation.history_revision += 1
        await db.commit()

    # ---- ① 开头持久化用户消息（message-as-log，刷新可回放）----
    # C8：用户消息 + 附件回填 + touch 合并为单事务（原 3 次独立 commit，D10 同事务偏差）
    att_refs: list[dict[str, Any]] = []
    att_repo = AttachmentRepository(db)
    for aid in attachments or []:
        try:
            row = await att_repo.get(user.id, uuid.UUID(str(aid)))
        except (AttributeError, ValueError):
            row = None
        if row is None:
            att_refs.append({"attachment_id": str(aid)})
        else:
            att_refs.append(
                {
                    "attachment_id": str(row.id),
                    "name": row.filename,
                    "mime_type": row.content_type,
                    "size": row.size_bytes,
                    "status": row.status,
                }
            )
    att_refs = att_refs or []
    persisted_file_refs = [{"path": path} for path in (file_refs or [])]
    user_msg = await msg_repo.create(
        message_id=user_message_id,
        conversation_id=conversation.id,
        role="user",
        content=content,
        attachments=att_refs,
        file_refs=persisted_file_refs,
        trace_id=trace_id,
        checkpoint_id=checkpoint.id,
        history_parent_id=previous_head,
    )
    await db.flush()  # uuid4 default 在 flush 应用——回填需 user_msg.id（C8 单事务内不 commit）
    if att_refs:
        await _backfill_attachments(db, [a["attachment_id"] for a in att_refs], conversation.id, user_msg.id)
    await ConversationRepository(db).touch_last_message(conversation.id)
    conversation.active_message_head_id = user_msg.id
    conversation.message_cursor_initialized = True
    conversation.history_revision += 1
    # 标题兜底：默认标题会话（新建按钮/API 创建）在首条消息后自动用首句命名（与前端 truncate 同语义）
    if conversation.title == "新会话" and content.strip():
        conversation.title = _title_from(content)
    if task is not None:
        task.input = {
            **(task.input or {}),
            "user_message_id": str(user_msg.id),
            "checkpoint_id": str(checkpoint.id),
        }
    await db.commit()

    if await _task_cancelled():
        await checkpoint_service.seal_checkpoint(conversation.id, checkpoint.id, interrupted=True)
        await _clear_prestart_cancel()
        return

    assistant_msg_id = uuid.uuid4()
    message_start_payload = {
        "message_id": str(assistant_msg_id),
        "agent_id": str(agent.id),
        "conversation_id": str(conversation.id),
        "task_id": str(task.id) if task is not None else None,
        "user_message_id": str(user_msg.id),
        "checkpoint_id": str(checkpoint.id),
    }
    if task is not None:
        await push_event(str(task.id), "message_start", message_start_payload)
    yield emit("message_start", message_start_payload)

    graph_config = _graph_config(
        thread_id=str(conversation.id),
        trace_id=trace_id,
        assistant_msg_id=assistant_msg_id,
        model_override=model_override,
        image_context=prepared_images,
        document_context=prepared_documents,
        checkpoint_id=checkpoint.id,
        graph_parent_checkpoint_id=graph_parent_checkpoint_id,
        start_graph_from_root=start_graph_from_root,
    )

    async def _bind_graph_run() -> None:
        resolver = getattr(graph_checkpointer, "aget_run_bounds", None)
        if resolver is None:
            return
        parent_id, output_id = await resolver(
            {"configurable": {"thread_id": str(conversation.id)}}, str(checkpoint.id)
        )
        await checkpoint_service.store.bind_graph_run(
            conversation.id,
            checkpoint.id,
            graph_parent_checkpoint_id=parent_id,
            graph_parent_bound=True,
            graph_output_checkpoint_id=output_id,
        )
        conversation.active_graph_checkpoint_id = output_id
        conversation.graph_cursor_initialized = True

    async def on_interrupt(value: dict[str, Any]) -> str:
        nonlocal task
        await _bind_graph_run()
        if task is not None:
            await TaskService().set_waiting_confirm(
                db,
                task,
                value=value,
                conversation_id=conversation.id,
                thread_id=str(conversation.id),
            )
        else:
            # 兼容不经过 HTTP 路由的旧调用方/单测。
            task = await TaskService().create_waiting_confirm(
                db,
                user=user,
                agent_id=agent.id,
                input={
                    "message": content,
                    "attachment_ids": list(attachments or []),
                    "file_refs": persisted_file_refs,
                    "document_refs": list(prepared_documents.refs),
                    "user_message_id": str(user_msg.id),
                    "checkpoint_id": str(checkpoint.id),
                },
                value=value,
                conversation_id=conversation.id,
                thread_id=str(conversation.id),
            )
        return emit(
            "interrupt",
            {
                "node_id": value.get("node_id"),
                "payload": value,
                "confirm_required": True,
                "task_id": str(task.id),
            },
        )

    async def on_final(final_state: dict[str, Any]) -> dict[str, Any]:
        # ---- ② 流结束：只补最终轮（round_sink 轮已在流中即时落库）+ run_logs + last_message_at ----
        if task is not None:
            current_task = await TaskRepository(db).get_by_id(task.id)
            if current_task is None or current_task.status == "cancelled":
                # 取消与 done 竞态：取消获胜时禁止补 assistant 消息/覆盖任务终态。
                await checkpoint_service.seal_checkpoint(conversation.id, checkpoint.id, interrupted=True)
                return {}
        await _bind_graph_run()
        fm = final_state.get("final_message", {}) or {}
        totals = final_state.get("totals") or {}
        # 最终轮推理（最后一条 AI 消息的 reasoning_content）
        last_ai = next(
            (m for m in reversed(final_state.get("messages", [])) if getattr(m, "type", "") == "ai"), None
        )
        final_thinking = (
            ((getattr(last_ai, "additional_kwargs", {}) or {}).get("reasoning_content") or "") if last_ai else ""
        )
        final_row = await msg_repo.create(
            message_id=assistant_msg_id,
            conversation_id=conversation.id,
            role="assistant",
            content=fm.get("content", ""),
            thinking=final_thinking,
            tool_calls=[],  # 最终轮本身无工具
            token_usage=fm.get("token_usage") or totals,
            parent_id=user_msg.id,
            history_parent_id=conversation.active_message_head_id,
            trace_id=trace_id,
            round=len(round_sink) + 1,
        )
        conversation.active_message_head_id = final_row.id
        conversation.active_code_node_id = checkpoint.id
        conversation.graph_cursor_initialized = True
        conversation.history_revision += 1
        for log in final_state.get("run_logs", []):
            await RunLogRepository(db).create(session_id=conversation.id, **log)
        await ConversationRepository(db).touch_last_message(conversation.id)
        await db.commit()
        await checkpoint_service.store.seal_checkpoint(conversation.id, checkpoint.id)
        # 主动记忆：流结束 spawn 后台提取分支（独立 LLM 推理，不阻塞 SSE；resume 续流不触发防重复评估）
        _spawn_memory_extract(final_state, user, trace_id, conversation.id, workspace)
        payload = _done_payload(assistant_msg_id, fm.get("token_usage") or totals, serialize_message(final_row))
        # 收口兜底标记（2026-08-24）：步数守卫强制退出 → 前端可提示答复可能不完整
        if (final_state.get("flags") or {}).get("max_steps_exceeded"):
            payload["note"] = "已达步数上限，答复可能不完整"
        if task is not None:
            current_task = await TaskRepository(db).get_by_id(task.id)
            if current_task is not None and current_task.status != "cancelled":
                await TaskService().set_done(
                    db, current_task, final_message=payload["message"], _lock_held=True
                )
                await push_event(
                    str(task.id),
                    "done",
                    {
                        "message_id": str(assistant_msg_id),
                        "token_usage": payload.get("token_usage"),
                        "message": payload["message"],
                    },
                )
        return payload

    async def on_error(exc: Exception) -> None:
        await checkpoint_service.store.seal_checkpoint(conversation.id, checkpoint.id, interrupted=True)
        with contextlib.suppress(Exception):
            await _bind_graph_run()
        if task is None:
            return
        await db.rollback()
        current_task = await TaskRepository(db).get_by_id(task.id)
        if current_task is not None and current_task.status != "cancelled":
            error_payload = {
                "code": getattr(exc, "code", 60001),
                "message": getattr(exc, "message", str(exc)),
                "kind": getattr(exc, "kind", None),
                "retryable": getattr(exc, "retryable", False),
                "recoverable": getattr(exc, "recoverable", False),
                "details": getattr(exc, "details", {}),
            }
            await TaskService().set_failed(db, current_task, error_payload, _lock_held=True)
            details = error_payload["details"]
            await RunLogRepository(db).create(
                session_id=conversation.id,
                trace_id=trace_id,
                node="agent_execute",
                type="llm",
                input={"model": details.get("model"), "context_metrics": details.get("context_metrics")},
                output={"kind": error_payload["kind"], "details": details},
                duration_ms=int(details.get("elapsed_ms") or 0),
                status="error",
            )
            await push_event(
                str(task.id),
                "error",
                {
                    "code": getattr(exc, "code", 60001),
                    "message": getattr(exc, "message", str(exc)),
                    "kind": getattr(exc, "kind", None),
                    "retryable": getattr(exc, "retryable", False),
                    "recoverable": getattr(exc, "recoverable", False),
                    "details": getattr(exc, "details", {}),
                },
            )

    async def _guarded_final(final_state: dict[str, Any]) -> dict[str, Any]:
        if task is None:
            return await on_final(final_state)
        from app.orchestration.task_worker import task_guard

        async with task_guard(str(task.id)):
            return await on_final(final_state)

    async def _guarded_error(exc: Exception) -> None:
        if task is None:
            return await on_error(exc)
        from app.orchestration.task_worker import task_guard

        async with task_guard(str(task.id)):
            await on_error(exc)

    async def _task_event_sink(event_type: str, payload: dict[str, Any]) -> None:
        if task is not None:
            await push_event(str(task.id), event_type, payload)

    async for frame in stream_graph_events(
        graph=graph,
        initial=build_initial_state(
            agent,
            content,
            user_id=str(user.id),
            org_id=str(agent.org_id),
            enabled_tool_ids=await ToolService().enabled_tool_ids(db, agent.org_id),
            workspace=workspace,
            image_refs=list(prepared_images.image_refs) or None,
            image_candidate_count=prepared_images.candidate_count,
            image_omitted_count=prepared_images.omitted_count,
            image_capability=prepared_images.capability,
            document_refs=list(prepared_documents.refs) or None,
        ),
        graph_config=graph_config,
        emit=emit,
        on_interrupt=on_interrupt,
        on_final=_guarded_final,
        on_error=_guarded_error,
        task_event_sink=_task_event_sink,
        round_sink=round_sink,
        on_round_message=_persist_round,
        run_id=str(task.id) if task is not None else None,
    ):
        yield frame


async def resume_stream_events(
    *,
    db: Any,
    graph: Any,
    task: Task,
    user: User,
    approved: bool,
    trace_id: str,
    model_override: Any = None,
    recovery: bool = False,
) -> AsyncIterator[str]:
    """中断恢复（docs 03 §5.3 resume）：读 pending_confirm → 恢复 thread → SSE 续流。

    前置状态迁移：approved → running；denied → cancelled（流仍输出 LLM 致歉文本）。
    前端硬约束：续流不得发 message_start（会重置 segments 清掉工具卡）。
    """
    emit = sse_emitter()
    pending = task.pending_confirm or {}
    thread_id = (
        TaskService.resolve_execution_thread(task) if recovery else TaskService.resolve_resume_thread(task)
    )
    conversation_raw = (
        (task.input or {}).get("conversation_id") if recovery else pending.get("conversation_id")
    )
    conversation_id = uuid.UUID(conversation_raw) if conversation_raw else None
    task_service = TaskService()
    checkpoint_service = get_checkpoint_service(
        get_settings().agent_data_dir, get_settings().checkpoint_retention_days
    )
    checkpoint_id: uuid.UUID | None = None
    raw_checkpoint = (task.input or {}).get("checkpoint_id")
    if raw_checkpoint:
        try:
            checkpoint_id = uuid.UUID(str(raw_checkpoint))
        except (AttributeError, ValueError):
            checkpoint_id = None
    conversation_row = None
    if conversation_id:
        conversation_row = await ConversationRepository(db).table.get(conversation_id)

    # checkpoint 只保存轻量 document_ref；恢复时按 task input 重新读取当前轮正文，
    # 并以原 ref_id 绑定，避免 document_ref 原样落到模型 provider。
    resume_documents = await prepare_resume_document_context(
        db,
        user_id=user.id,
        org_id=user.org_id,
        conversation_id=conversation_id,
        task_input=task.input,
    )

    assistant_msg_id = uuid.uuid4()
    if approved:
        if not recovery:
            await task_service.set_running(db, task)
        pending_tool = str(pending.get("tool_name") or pending.get("name") or pending.get("node_id") or "tool")
        if recovery:
            yield emit(
                "status",
                {"status": "retrying", "phase": "reconnecting", "accepted": True, "message": "正在从断点继续"},
            )
            retry_start_payload = {
                "message_id": str(assistant_msg_id),
                "task_id": str(task.id),
                "retry_of_task_id": str(task.id),
            }
            await push_event(str(task.id), "message_start", retry_start_payload)
            yield emit("message_start", retry_start_payload)
        else:
            yield emit(
                "status",
                {
                    "status": "running",
                    "phase": "tool",
                    "detail": pending_tool,
                    "tool_name": pending_tool,
                    "tool_call_id": pending.get("tool_call_id"),
                    "accepted": True,
                    "message": "已确认，正在执行",
                },
            )
    else:
        await task_service.set_cancelled(db, task)
        yield emit(
            "status",
            {
                "status": "cancelling",
                "phase": "cancelling",
                "accepted": True,
                "message": "已拒绝，正在取消操作",
            },
        )

    round_sink: list[dict[str, Any]] = []
    parent_id = None
    round_offset = 0
    if recovery and conversation_id:
        raw_parent = (task.input or {}).get("user_message_id")
        try:
            parent_id = uuid.UUID(str(raw_parent)) if raw_parent else None
        except (AttributeError, ValueError):
            parent_id = None
        existing = await MessageRepository(db).list_by_conversation(conversation_id)
        round_offset = max((int(m.round or 0) for m in existing if parent_id and m.parent_id == parent_id), default=0)

    async def _persist_round(round_msg: dict[str, Any]) -> None:
        """即时落库（docs 03 §3）：resume 续流每轮同步写该轮 Message（会话流才落库）。"""
        if not conversation_id:
            return
        row = await MessageRepository(db).create(
            message_id=uuid.UUID(round_msg["id"]),
            conversation_id=conversation_id,
            role="assistant",
            content=round_msg["content"],
            thinking=round_msg.get("thinking") or "",
            tool_calls=round_msg["tool_calls"],
            token_usage=round_msg.get("token_usage"),
            parent_id=parent_id,
            history_parent_id=conversation_row.active_message_head_id if conversation_row else None,
            trace_id=trace_id,
            round=round_offset + round_msg["round"],
        )
        if conversation_row is not None:
            conversation_row.active_message_head_id = row.id
            conversation_row.history_revision += 1
        await db.commit()

    recovery_images = None
    if recovery:
        attachment_ids = (task.input or {}).get("attachment_ids", [])
        if not isinstance(attachment_ids, list):
            attachment_ids = []
        recovery_agent = await AgentRepository(db).get_by_id(task.agent_id)
        recovery_images = await prepare_image_input(
            db,
            user_id=user.id,
            attachment_ids=[str(value) for value in attachment_ids],
            effective_model=recovery_agent.model if recovery_agent else "",
        )
    graph_config = _graph_config(
        thread_id=str(thread_id),
        trace_id=trace_id,
        assistant_msg_id=assistant_msg_id,
        model_override=model_override,
        image_context=recovery_images,
        # 普通 resume 的图片 b64 载荷不落 checkpoint；恢复任务则重新安全读取 owner 附件。
        force_image_context=not recovery,
        document_context=resume_documents,
        checkpoint_id=checkpoint_id,
    )

    graph_checkpointer = getattr(graph, "checkpointer", None)

    async def _bind_graph_run() -> None:
        """Bind the real graph output for the code anchor, including resumed runs."""
        if checkpoint_id is None:
            return
        resolver = getattr(graph_checkpointer, "aget_run_bounds", None)
        if resolver is None:
            return
        parent_graph_id, output_graph_id = await resolver(
            {"configurable": {"thread_id": str(thread_id)}}, str(checkpoint_id)
        )
        if conversation_id:
            await checkpoint_service.store.bind_graph_run(
                conversation_id,
                checkpoint_id,
                graph_parent_checkpoint_id=parent_graph_id,
                graph_parent_bound=True,
                graph_output_checkpoint_id=output_graph_id,
            )
            if conversation_row is not None:
                conversation_row.active_graph_checkpoint_id = output_graph_id
                conversation_row.graph_cursor_initialized = True

    async def on_interrupt(value: dict[str, Any]) -> str:
        # 二次中断：再建新 Task 承接（同一 thread 继续）
        await _bind_graph_run()
        if recovery:
            await task_service.set_waiting_confirm(
                db,
                task,
                value=value,
                conversation_id=conversation_id,
                thread_id=str(thread_id),
            )
            return emit(
                "interrupt",
                {"node_id": value.get("node_id"), "payload": value, "confirm_required": True, "task_id": str(task.id)},
            )
        new_task = await task_service.create_waiting_confirm(
            db,
            user=user,
            agent_id=task.agent_id,
            input=task.input or {},
            value=value,
            conversation_id=conversation_id,
            thread_id=str(thread_id),
        )
        return emit(
            "interrupt",
            {
                "node_id": value.get("node_id"),
                "payload": value,
                "confirm_required": True,
                "task_id": str(new_task.id),
            },
        )

    async def on_final(final_state: dict[str, Any]) -> dict[str, Any]:
        await _bind_graph_run()
        fm = final_state.get("final_message", {}) or {}
        totals = final_state.get("totals") or {}
        assistant_msg: Message | None = None
        if conversation_id:
            # 会话流：只补最终轮（round_sink 轮已在流中即时落库）+ run_logs + touch（任务流无会话，只更新任务状态）
            msg_repo = MessageRepository(db)
            last_ai = next(
                (m for m in reversed(final_state.get("messages", [])) if getattr(m, "type", "") == "ai"), None
            )
            final_thinking = (
                ((getattr(last_ai, "additional_kwargs", {}) or {}).get("reasoning_content") or "") if last_ai else ""
            )
            assistant_msg = await msg_repo.create(
                message_id=assistant_msg_id,
                conversation_id=conversation_id,
                role="assistant",
                content=fm.get("content", ""),
                thinking=final_thinking,
                tool_calls=[],
                token_usage=fm.get("token_usage") or totals,
                trace_id=trace_id,
                parent_id=parent_id,
                history_parent_id=conversation_row.active_message_head_id if conversation_row else None,
                round=round_offset + len(round_sink) + 1,
            )
            if conversation_row is not None:
                conversation_row.active_message_head_id = assistant_msg.id
                conversation_row.history_revision += 1
            for log in final_state.get("run_logs", []):
                await RunLogRepository(db).create(session_id=conversation_id, **log)
            await ConversationRepository(db).touch_last_message(conversation_id)
            if checkpoint_id is not None and conversation_row is not None:
                conversation_row.active_code_node_id = checkpoint_id
        # F10：重读任务行，避免覆盖并发取消（与 task_run 一致）
        updated = await TaskRepository(db).get_by_id(task.id)
        if updated is not None and updated.status != "cancelled":
            await task_service.set_done(db, updated, final_message=fm)  # set_done 内部 commit（含消息持久化）
            await push_event(
                str(task.id),
                "done",
                {"message_id": str(assistant_msg_id), "token_usage": fm.get("token_usage") or totals, "message": fm},
            )
        elif updated is not None:
            await push_event(str(task.id), "cancelled", {"status": "cancelled"})
            await db.commit()  # 拒绝分支无 set_done：此处落消息持久化（E5）
        if checkpoint_id is not None and conversation_id:
            await checkpoint_service.store.seal_checkpoint(conversation_id, checkpoint_id)
        # 2d：demo_notify 确认执行后落通知（工具结果产生源）
        await maybe_notify_from_tool_results(db, user.id, final_state)
        # 主动记忆：resume 完成同样触发提取（首次流中断时 on_final 未执行；提取按最后 user
        # 消息取尾部，天然不重复评估旧轮次；resume 无 workspace 上下文 → 只落全局）
        if conversation_id:
            _spawn_memory_extract(final_state, user, trace_id, conversation_id, None)
        return _done_payload(
            assistant_msg_id,
            fm.get("token_usage") or totals,
            serialize_message(assistant_msg) if assistant_msg else None,
        )

    async def on_error(exc: Exception) -> None:
        # F5：SSE 轨 resume 图级异常 → 任务置 failed（与 task_run 一致）
        # E1：on_final 落库失败会毒化 session → 先 rollback，防 set_failed 也失败
        await db.rollback()
        with contextlib.suppress(Exception):
            await _bind_graph_run()
        if checkpoint_id is not None and conversation_id:
            await checkpoint_service.store.seal_checkpoint(conversation_id, checkpoint_id, interrupted=True)
        updated = await TaskRepository(db).get_by_id(task.id)
        if updated is not None and updated.status == "running":
            error_payload = {
                "code": getattr(exc, "code", 60001),
                "message": getattr(exc, "message", str(exc)),
                "kind": getattr(exc, "kind", None),
                "retryable": getattr(exc, "retryable", False),
                "recoverable": getattr(exc, "recoverable", False),
                "details": getattr(exc, "details", {}),
            }
            await task_service.set_failed(db, updated, error_payload)
            details = error_payload["details"]
            await RunLogRepository(db).create(
                task_id=task.id,
                trace_id=trace_id,
                node="agent_execute",
                type="llm",
                input={"model": details.get("model"), "context_metrics": details.get("context_metrics")},
                output={"kind": error_payload["kind"], "details": details},
                duration_ms=int(details.get("elapsed_ms") or 0),
                status="error",
            )
            await push_event(
                str(task.id),
                "error",
                {
                    "code": getattr(exc, "code", 60001),
                    "message": getattr(exc, "message", str(exc)),
                    "kind": getattr(exc, "kind", None),
                    "retryable": getattr(exc, "retryable", False),
                    "recoverable": getattr(exc, "recoverable", False),
                    "details": getattr(exc, "details", {}),
                },
            )

    async def _task_event_sink(event_type: str, payload: dict[str, Any]) -> None:
        await push_event(str(task.id), event_type, payload)

    async for frame in stream_graph_events(
        graph=graph,
        initial=None if recovery else Command(resume={"approved": approved}),
        graph_config=graph_config,
        emit=emit,
        on_interrupt=on_interrupt,
        on_final=on_final,
        on_error=on_error,
        task_event_sink=_task_event_sink,
        round_sink=round_sink,
        on_round_message=_persist_round,
        run_id=str(task.id),
    ):
        yield frame


async def retry_stream_events(
    *,
    db: Any,
    graph: Any,
    task: Task,
    user: User,
    trace_id: str,
    model_override: Any = None,
) -> AsyncIterator[str]:
    """普通聊天的 checkpoint 恢复流；与 confirmation resume 分离，initial=None。"""
    async for frame in resume_stream_events(
        db=db,
        graph=graph,
        task=task,
        user=user,
        approved=True,
        trace_id=trace_id,
        model_override=model_override,
        recovery=True,
    ):
        yield frame


async def agent_invoke_events(
    *,
    db: Any,
    graph: Any,
    agent: AgentConfig,
    user: User,
    content: str,
    trace_id: str,
    model_override: Any = None,
) -> AsyncIterator[str]:
    """Agent 试跑（docs 03 §5.4 invoke）：轻量路径——不建会话、不落消息，thread_id=uuid4()。

    中断同样建 Task 承接（conversation_id=None），resume 走任务端点续流。
    """
    emit = sse_emitter()
    thread_id = str(uuid.uuid4())
    assistant_msg_id = uuid.uuid4()
    yield emit(
        "message_start",
        {
            "message_id": str(assistant_msg_id),
            "agent_id": str(agent.id),
            "conversation_id": thread_id,  # 仅展示用（无持久化会话）
        },
    )

    graph_config = _graph_config(
        thread_id=thread_id,
        trace_id=trace_id,
        assistant_msg_id=assistant_msg_id,
        model_override=model_override,
    )

    async def on_interrupt(value: dict[str, Any]) -> str:
        task = await TaskService().create_waiting_confirm(
            db,
            user=user,
            agent_id=agent.id,
            input={"message": content},
            value=value,
            conversation_id=None,
            thread_id=thread_id,
        )
        return emit(
            "interrupt",
            {
                "node_id": value.get("node_id"),
                "payload": value,
                "confirm_required": True,
                "task_id": str(task.id),
            },
        )

    async def on_final(final_state: dict[str, Any]) -> dict[str, Any]:
        # 不落库：message = final_message 快照（AgentTestRunner 无持久化场景）
        fm = final_state.get("final_message", {}) or {}
        totals = final_state.get("totals") or {}
        return _done_payload(assistant_msg_id, fm.get("token_usage") or totals, fm)

    async for frame in stream_graph_events(
        graph=graph,
        # agent_invoke（AgentTestRunner 轻量路径）暂不接收附件入参；
        # 接法同 chat_stream_events：attachment_mimes → 读盘+b64 → _graph_config(image_payload=…) + image_refs
        initial=build_initial_state(
            agent,
            content,
            user_id=str(user.id),
            org_id=str(agent.org_id),
            enabled_tool_ids=await ToolService().enabled_tool_ids(db, agent.org_id),
        ),
        graph_config=graph_config,
        emit=emit,
        on_interrupt=on_interrupt,
        on_final=on_final,
    ):
        yield frame
