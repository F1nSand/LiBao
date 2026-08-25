"""Graph→SSE 桥（docs 03 §3.3，M1 核心 + M2 interrupt/resume）。

职责（docs 01 §5.2）：graph.astream → SSE 事件信封（共享循环在 stream_core.py）；
消息持久化在此（节点保持无 DB）：开头落用户消息，流结束落 assistant 最终消息 + run_logs + last_message_at。
M2：require_confirm 工具 → interrupt 事件（自动建 Task 承接）→ POST /tasks/{id}/resume → resume_stream_events 续流。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.types import Command

from app.core.events import sse_emitter
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

logger = logging.getLogger(__name__)


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
    *, thread_id: str, trace_id: str, assistant_msg_id: uuid.UUID, model_override: Any = None
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "trace_id": trace_id,
            "assistant_msg_id": str(assistant_msg_id),
        }
    }
    if model_override is not None:
        cfg["configurable"]["model"] = model_override
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
    workspace: dict[str, Any] | None = None,
    trace_id: str,
    model_override: Any = None,
) -> AsyncIterator[str]:
    emit = sse_emitter()
    msg_repo = MessageRepository(db)
    # 逐轮消息收集（docs 03 §3 多消息扩展）：stream_core 每轮工具结果齐后 append + 即时落库
    round_sink: list[dict[str, Any]] = []

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
            trace_id=trace_id,
            round=round_msg["round"],
        )
        row.id = uuid.UUID(round_msg["id"])
        await db.commit()

    # ---- ① 开头持久化用户消息（message-as-log，刷新可回放）----
    # C8：用户消息 + 附件回填 + touch 合并为单事务（原 3 次独立 commit，D10 同事务偏差）
    att_refs = [{"attachment_id": aid} for aid in (attachments or [])] or None
    user_msg = await msg_repo.create(
        conversation_id=conversation.id, role="user", content=content, attachments=att_refs, trace_id=trace_id
    )
    await db.flush()  # uuid4 default 在 flush 应用——回填需 user_msg.id（C8 单事务内不 commit）
    if att_refs:
        await _backfill_attachments(db, [a["attachment_id"] for a in att_refs], conversation.id, user_msg.id)
    await ConversationRepository(db).touch_last_message(conversation.id)
    # 标题兜底：默认标题会话（新建按钮/API 创建）在首条消息后自动用首句命名（与前端 truncate 同语义）
    if conversation.title == "新会话" and content.strip():
        conversation.title = _title_from(content)
    await db.commit()

    assistant_msg_id = uuid.uuid4()
    yield emit(
        "message_start",
        {
            "message_id": str(assistant_msg_id),
            "agent_id": str(agent.id),
            "conversation_id": str(conversation.id),
        },
    )

    graph_config = _graph_config(
        thread_id=str(conversation.id),
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
            conversation_id=conversation.id,
            role="assistant",
            content=fm.get("content", ""),
            thinking=final_thinking,
            tool_calls=[],  # 最终轮本身无工具
            token_usage=fm.get("token_usage") or totals,
            parent_id=user_msg.id,
            trace_id=trace_id,
            round=len(round_sink) + 1,
        )
        final_row.id = assistant_msg_id
        for log in final_state.get("run_logs", []):
            await RunLogRepository(db).create(session_id=conversation.id, **log)
        await ConversationRepository(db).touch_last_message(conversation.id)
        await db.commit()
        # 主动记忆：流结束 spawn 后台提取分支（独立 LLM 推理，不阻塞 SSE；resume 续流不触发防重复评估）
        _spawn_memory_extract(final_state, user, trace_id, conversation.id, workspace)
        payload = _done_payload(assistant_msg_id, fm.get("token_usage") or totals, serialize_message(final_row))
        # 收口兜底标记（2026-08-24）：步数守卫强制退出 → 前端可提示答复可能不完整
        if (final_state.get("flags") or {}).get("max_steps_exceeded"):
            payload["note"] = "已达步数上限，答复可能不完整"
        return payload

    async for frame in stream_graph_events(
        graph=graph,
        initial=build_initial_state(
            agent,
            content,
            user_id=str(user.id),
            org_id=str(agent.org_id),
            enabled_tool_ids=await ToolService().enabled_tool_ids(db, agent.org_id),
            workspace=workspace,
        ),
        graph_config=graph_config,
        emit=emit,
        on_interrupt=on_interrupt,
        on_final=on_final,
        round_sink=round_sink,
        on_round_message=_persist_round,
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
) -> AsyncIterator[str]:
    """中断恢复（docs 03 §5.3 resume）：读 pending_confirm → 恢复 thread → SSE 续流。

    前置状态迁移：approved → running；denied → cancelled（流仍输出 LLM 致歉文本）。
    前端硬约束：续流不得发 message_start（会重置 segments 清掉工具卡）。
    """
    emit = sse_emitter()
    pending = task.pending_confirm or {}
    thread_id = TaskService.resolve_resume_thread(task)
    conversation_id = uuid.UUID(pending["conversation_id"]) if pending.get("conversation_id") else None
    task_service = TaskService()

    if approved:
        await task_service.set_running(db, task)
    else:
        await task_service.set_cancelled(db, task)

    assistant_msg_id = uuid.uuid4()
    round_sink: list[dict[str, Any]] = []

    async def _persist_round(round_msg: dict[str, Any]) -> None:
        """即时落库（docs 03 §3）：resume 续流每轮同步写该轮 Message（会话流才落库）。"""
        if not conversation_id:
            return
        row = await MessageRepository(db).create(
            conversation_id=conversation_id,
            role="assistant",
            content=round_msg["content"],
            thinking=round_msg.get("thinking") or "",
            tool_calls=round_msg["tool_calls"],
            token_usage=round_msg.get("token_usage"),
            trace_id=trace_id,
            round=round_msg["round"],
        )
        row.id = uuid.UUID(round_msg["id"])
        await db.commit()

    graph_config = _graph_config(
        thread_id=str(thread_id),
        trace_id=trace_id,
        assistant_msg_id=assistant_msg_id,
        model_override=model_override,
    )

    async def on_interrupt(value: dict[str, Any]) -> str:
        # 二次中断：再建新 Task 承接（同一 thread 继续）
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
                conversation_id=conversation_id,
                role="assistant",
                content=fm.get("content", ""),
                thinking=final_thinking,
                tool_calls=[],
                token_usage=fm.get("token_usage") or totals,
                trace_id=trace_id,
                round=len(round_sink) + 1,
            )
            assistant_msg.id = assistant_msg_id
            for log in final_state.get("run_logs", []):
                await RunLogRepository(db).create(session_id=conversation_id, **log)
            await ConversationRepository(db).touch_last_message(conversation_id)
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
        updated = await TaskRepository(db).get_by_id(task.id)
        if updated is not None and updated.status == "running":
            await task_service.set_failed(db, updated, str(exc))
            await push_event(str(task.id), "error", {"code": 60001, "message": str(exc), "retryable": True})

    async for frame in stream_graph_events(
        graph=graph,
        initial=Command(resume={"approved": approved}),
        graph_config=graph_config,
        emit=emit,
        on_interrupt=on_interrupt,
        on_final=on_final,
        on_error=on_error,
        round_sink=round_sink,
        on_round_message=_persist_round,
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
