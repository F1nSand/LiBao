"""Graph→SSE 桥（docs 03 §3.3，T10 M1 核心）。

职责（docs 01 §5.2）：graph.astream(stream_mode=["messages","updates","values"]) → SSE 事件信封；
消息持久化在此（节点保持无 DB）：开头落用户消息，流结束落 assistant 最终消息 + run_logs + last_message_at。
keepalive 注释 15s；seq 单调从 1 起；done/error 后关闭流；客户端断开 → 取消 producer（中止 graph）。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_LLM_FAILURE
from app.core.events import format_sse, make_event
from app.storage.models.agent import AgentConfig
from app.storage.models.conversation import Conversation
from app.storage.models.message import Message
from app.storage.models.user import User
from app.storage.repositories.conversation import ConversationRepository
from app.storage.repositories.message import MessageRepository
from app.storage.repositories.run_log import RunLogRepository

logger = logging.getLogger(__name__)

KEEPALIVE_INTERVAL = 15


def _chunk_text(chunk: Any) -> str:
    """从 AIMessageChunk 提取 text（兼容 content 为 str 或 content blocks 列表；跳过 thinking 块）。"""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _message_dict(msg: Message) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "role": msg.role,
        "content": msg.content,
        "tool_calls": msg.tool_calls or [],
        "token_usage": msg.token_usage,
        "attachments": msg.attachments or [],
        "trace_id": msg.trace_id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


async def chat_stream_events(
    *,
    db: AsyncSession,
    graph: Any,
    conversation: Conversation,
    agent: AgentConfig,
    user: User,
    content: str,
    trace_id: str,
    model_override: Any = None,
) -> AsyncIterator[str]:
    seq = 0

    def emit(event_type: str, payload: dict[str, Any]) -> str:
        nonlocal seq
        seq += 1
        return format_sse(make_event(event_type, payload, seq))

    msg_repo = MessageRepository(db)

    # ---- ① 开头持久化用户消息（message-as-log，刷新可回放）----
    user_msg = await msg_repo.create(
        conversation_id=conversation.id, role="user", content=content, trace_id=trace_id
    )
    await db.commit()
    await ConversationRepository(db).touch_last_message(conversation.id)
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

    initial: dict[str, Any] = {
        "messages": [HumanMessage(content=content)],
        "agent_config": {
            "model": agent.model,
            "system_prompt": agent.system_prompt,
            "tools": agent.tools or [],
            "max_steps": agent.max_steps,
        },
        "flags": {"steps": 0},
    }
    graph_config: dict[str, Any] = {
        "configurable": {
            "thread_id": str(conversation.id),
            "trace_id": trace_id,
            "assistant_msg_id": str(assistant_msg_id),
        }
    }
    if model_override is not None:
        graph_config["configurable"]["model"] = model_override

    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    async def producer() -> None:
        try:
            async for item in graph.astream(initial, graph_config, stream_mode=["messages", "updates", "values"]):
                await queue.put(("item", item))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("chat stream graph failed")
            await queue.put(("graph_error", exc))
        finally:
            await queue.put(("eof", None))

    async def keepalive() -> None:
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                await queue.put(("keepalive", None))
        except asyncio.CancelledError:
            pass

    producer_task = asyncio.create_task(producer())
    keepalive_task = asyncio.create_task(keepalive())
    final_state: dict[str, Any] | None = None
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "keepalive":
                yield ": keepalive\n\n"
                continue
            if kind == "eof":
                break
            if kind == "graph_error":
                yield emit("error", {"code": ERR_LLM_FAILURE, "message": str(payload), "retryable": False})
                return

            mode, item = payload
            if mode == "messages":
                chunk, meta = item
                if meta.get("langgraph_node") == "agent_execute":
                    text = _chunk_text(chunk)
                    if text:
                        yield emit("token", {"text": text})
            elif mode == "updates":
                for node, update in item.items():
                    if node == "agent_execute":
                        for m in update.get("messages", []):
                            for tc in getattr(m, "tool_calls", []) or []:
                                yield emit(
                                    "tool_call",
                                    {
                                        "tool_call_id": tc["id"],
                                        "tool_name": tc["name"],
                                        "input": tc.get("args", {}),
                                        "require_confirm": False,
                                    },
                                )
                    elif node == "tool_execute":
                        for r in update.get("tool_results", []):
                            yield emit(
                                "tool_result",
                                {
                                    "tool_call_id": r.get("tool_call_id"),
                                    "tool_name": r.get("tool_name"),
                                    "ok": r.get("ok"),
                                    "summary": r.get("summary", ""),
                                    "structured": r.get("output"),
                                    "placeholder": False,
                                    "job_ref": None,
                                    "duration_ms": r.get("duration_ms", 0),
                                },
                            )
                    elif node == "context_update":
                        yield emit("status", {"status": "finalizing", "context_metrics": None})
            elif mode == "values":
                final_state = item
    finally:
        producer_task.cancel()
        keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer_task

    if final_state is None:
        return

    # ---- ② 流结束：持久化 assistant 最终消息 + run_logs + last_message_at ----
    fm = final_state.get("final_message", {}) or {}
    totals = final_state.get("totals") or {}
    assistant_msg = await msg_repo.create(
        conversation_id=conversation.id,
        role="assistant",
        content=fm.get("content", ""),
        tool_calls=fm.get("tool_calls", []),
        token_usage=fm.get("token_usage") or totals,
        parent_id=user_msg.id,
        trace_id=trace_id,
    )
    assistant_msg.id = assistant_msg_id
    for log in final_state.get("run_logs", []):
        await RunLogRepository(db).create(session_id=conversation.id, **log)
    await ConversationRepository(db).touch_last_message(conversation.id)
    await db.commit()

    yield emit(
        "done",
        {
            "message_id": str(assistant_msg_id),
            "token_usage": fm.get("token_usage") or totals,
            "cost": totals.get("cost"),
            "message": _message_dict(assistant_msg),
        },
    )
