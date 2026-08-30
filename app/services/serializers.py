"""ORM → API 契约 dict（docs 03 §5 / FrontEnd types，字段 snake_case）。"""

from __future__ import annotations

from typing import Any

from app.storage.models.attachment import Attachment
from app.storage.models.conversation import Conversation
from app.storage.models.kb import KbCollection, KbDocument
from app.storage.models.mcp_server import McpServer
from app.storage.models.memory import LongTermMemory, LongTermMemoryVersion
from app.storage.models.message import Message
from app.storage.models.notification import Notification
from app.storage.models.run_log import RunLog
from app.storage.models.task import Task
from app.storage.models.tool_definition import ToolDefinition
from app.storage.models.user import User
from app.storage.models.workspace import Workspace
from app.tools.registry import get_by_name


def _dt(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_user(user: User, org_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "name": user.name,
        "username": user.username,
        "role": user.role,
        "org_id": str(user.org_id),
        "org_name": org_name,
        "enabled": user.enabled,
        "created_at": _dt(user.created_at),
    }


def serialize_conversation(conv: Conversation) -> dict[str, Any]:
    return {
        "id": str(conv.id),
        "user_id": str(conv.user_id),
        "agent_id": str(conv.agent_id),
        "title": conv.title,
        "status": conv.status,
        "max_messages": conv.max_messages,
        "workspace_id": str(conv.workspace_id) if conv.workspace_id else None,  # 工作区对话（M7-B）
        "last_message_at": _dt(conv.last_message_at),
        "created_at": _dt(conv.created_at),
        "active_message_head_id": str(conv.active_message_head_id) if conv.active_message_head_id else None,
        "message_cursor_initialized": conv.message_cursor_initialized,
        "active_graph_checkpoint_id": conv.active_graph_checkpoint_id,
        "graph_cursor_initialized": conv.graph_cursor_initialized,
        "active_code_node_id": str(conv.active_code_node_id) if conv.active_code_node_id else None,
        "history_revision": conv.history_revision,
    }


def serialize_message(msg: Message) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "role": msg.role,
        "content": msg.content,
        "thinking": getattr(msg, "thinking", None),  # 该轮推理（docs 03 §3 逐轮消息扩展）
        "attachments": msg.attachments or [],
        "file_refs": getattr(msg, "file_refs", None) or [],
        "tool_calls": msg.tool_calls or [],
        "token_usage": msg.token_usage,
        "cost": msg.token_usage.get("cost", 0.0) if isinstance(msg.token_usage, dict) else 0.0,
        "round": getattr(msg, "round", 1),  # 轮次（docs 03 §3 逐轮消息扩展）
        "trace_id": msg.trace_id,
        "checkpoint_id": str(msg.checkpoint_id) if getattr(msg, "checkpoint_id", None) else None,
        "history_parent_id": str(msg.history_parent_id) if getattr(msg, "history_parent_id", None) else None,
        "created_at": _dt(msg.created_at),
    }


def serialize_trajectory_node(m: Message, seq: int) -> dict[str, Any]:
    """消息 → TrajectoryNode（docs 03 §5.2.1 / FrontEnd TrajectoryNode）。"""
    tool_calls = [
        {
            "tool_call_id": tc.get("tool_call_id"),
            "tool_name": tc.get("tool_name"),
            "input": tc.get("input"),
            "output": tc.get("output"),
            "ok": tc.get("ok"),
            "duration_ms": tc.get("duration_ms", 0),
            "position": tc.get("position", 0),
        }
        for tc in (m.tool_calls or [])
    ]
    return {
        "seq": seq,
        "kind": m.role,  # user/assistant（context/steering/compaction 为 mock 扩展，真实无）
        "time": int(m.created_at.timestamp() * 1000) if m.created_at else 0,
        "content": m.content,
        "thinking": getattr(m, "thinking", None),  # 该轮推理（docs 03 §3 逐轮消息扩展）
        "diff": None,  # 无 context/system 更新差异
        "token_usage": m.token_usage,
        "trace_id": m.trace_id,
        "tool_calls": tool_calls,
    }


def serialize_tool_definition(t: ToolDefinition) -> dict[str, Any]:
    """工具序列化（docs 03 §5.5）。API id = registry spec.id（内置），无 spec 的 DB 工具 = "tl_" + name。"""
    spec = get_by_name(t.name)
    return {
        "id": spec.id if spec else f"tl_{t.name}",
        "name": t.name,
        "description": t.description,
        "params_schema": t.params_schema,
        "tool_type": t.tool_type,
        "enabled": t.enabled,
        "require_confirm": t.require_confirm,
        "sandbox": t.sandbox,
        "timeout_ms": t.timeout_ms,
        "max_concurrency": t.max_concurrency,
        "mcp_source": t.mcp_source,
        "idempotent": t.idempotent,
        "meta": spec.meta if spec else False,  # 元工具标记（前端工具页区分元工具/常规工具，docs 03 §5.5）
        "created_at": _dt(t.created_at),
    }


def serialize_workspace(w: Workspace) -> dict[str, Any]:
    """工作区序列化（M7-B，docs 03 §5.14 / FrontEnd Workspace）。"""
    return {
        "id": str(w.id),
        "org_id": str(w.org_id),
        "name": w.name,
        "description": w.description,
        "root_path": w.root_path,
        "project_instructions": w.project_instructions,
        "status": w.status,
        "created_by": str(w.created_by) if w.created_by else None,
        "created_at": _dt(w.created_at),
    }


def serialize_mcp_server(s: McpServer, tool_count: int = 0) -> dict[str, Any]:
    """MCP 源序列化（docs 03 §5.5 补充）。url_or_command 原样回显（command 或 url）。"""
    return {
        "id": str(s.id),
        "name": s.name,
        "transport": s.transport,
        "url_or_command": s.command or s.url,
        "headers": s.headers,
        "enabled": s.enabled,
        "tool_count": tool_count,
        "created_at": _dt(s.created_at),
    }


def serialize_attachment(a: Attachment) -> dict[str, Any]:
    """附件（docs 03 §5.9 / FrontEnd Attachment + UploadResponse）。

    S1：attachment_id 与 id 并存（前端 POST /uploads 消费 attachment_id，旧消费方读 id）。
    """
    return {
        "id": str(a.id),
        "attachment_id": str(a.id),
        "mime_type": a.content_type,
        "size": a.size_bytes,
        "status": a.status,
        "name": a.filename,
        "created_at": _dt(a.created_at),
    }


def serialize_kb_collection(c: KbCollection, document_count: int = 0) -> dict[str, Any]:
    """知识库集合（docs 03 §5.6 / FrontEnd KbCollection）。"""
    return {
        "id": str(c.id),
        "name": c.name,
        "description": c.description,
        "chunk_size": c.chunk_size,
        "overlap": c.chunk_overlap,
        "document_count": document_count,
        "created_at": _dt(c.created_at),
    }


def kb_document_progress(status: str) -> int:
    """KB 文档进度 0-100（S2 统一 number；前端 ChunkStatus 以 >=100 判成功，终端态一律 100）。"""
    return {"uploaded": 0, "chunking": 30, "indexing": 70}.get(status, 100)


def serialize_kb_document(d: KbDocument) -> dict[str, Any]:
    """知识库文档（docs 03 §5.6 / FrontEnd KbDocument）。"""
    return {
        "id": str(d.id),
        "collection_id": str(d.collection_id),
        "name": d.filename,
        "mime_type": d.content_type,
        "size": d.size_bytes,
        "status": d.status,
        "chunk_count": d.chunk_count,
        "progress": kb_document_progress(d.status),
        "error": d.error,
        "created_at": _dt(d.created_at),
    }


def serialize_longterm(card: LongTermMemory) -> dict[str, Any]:
    """长期记忆卡片（docs 03 §5.7 / FrontEnd LongTermMemory，body 对齐 content）。"""
    return {
        "id": str(card.id),
        "card_type": card.card_type,
        "title": card.title,
        "body": card.content,
        "tags": card.tags or [],
        "importance": card.importance,
        "workspace_id": str(card.workspace_id) if card.workspace_id else None,  # 工作区记忆（M7-B）
        "created_at": _dt(card.created_at),
        "updated_at": _dt(card.updated_at),
    }


def serialize_longterm_version(v: LongTermMemoryVersion, title: str | None = None) -> dict[str, Any]:
    """版本序列化（docs 03 §5.7 / FrontEnd LongTermMemoryVersion）。"""
    return {
        "id": str(v.id),
        "memory_id": str(v.memory_id),
        "version": v.version,
        "title": title,
        "body": v.content,
        "created_at": _dt(v.created_at),
    }


def serialize_notification(n: Notification) -> dict[str, Any]:
    """通知（docs 03 §5.11 / FrontEnd Notification）。"""
    return {
        "id": str(n.id),
        "title": n.title,
        "body": n.body,
        "level": n.level,
        "read": n.read,
        "created_at": _dt(n.created_at),
    }


def serialize_trace_event(log: RunLog) -> dict[str, Any]:
    """RunLog → TraceEvent（docs 03 §5.8 / FrontEnd TraceEvent）。"""
    return {
        "node_type": log.type,  # llm/tool/retrieval/memory/node
        "name": log.node,
        "status": "success" if log.status == "ok" else "failed",
        "token_usage": log.token_usage,
        "duration_ms": log.duration_ms,
        "input": log.input,
        "output": log.output,
        "ts": int(log.created_at.timestamp() * 1000) if log.created_at else 0,
    }


def serialize_run_log(log: RunLog) -> dict[str, Any]:
    """系统日志（docs 03 §5.8 / FrontEnd SystemLog）。level 由 status 映射（run_log 无 level 列）。"""
    level = {"ok": "INFO", "error": "ERROR", "retried": "WARNING"}.get(log.status, "INFO")
    out = log.output or {}
    message = str(out.get("content") or out.get("summary") or "")[:500] or None
    return {
        "id": str(log.id),
        "trace_id": log.trace_id,
        "level": level,
        "event": log.node,
        "service": "agent-backend",
        "message": message,
        "input": log.input,
        "output": log.output,
        "duration_ms": log.duration_ms,
        "created_at": _dt(log.created_at),
    }


def serialize_task(t: Task) -> dict[str, Any]:
    """任务序列化（docs 03 §5.3）。error 保留可恢复分类，兼容旧字符串消费者。"""
    error = t.error
    if isinstance(error, str):
        error = {"code": "task_error", "message": error, "retryable": False, "recoverable": False}
    return {
        "id": str(t.id),
        "agent_id": str(t.agent_id),
        "conversation_id": str(t.conversation_id) if t.conversation_id is not None else None,
        "recovery_graph_checkpoint_id": t.recovery_graph_checkpoint_id,
        "status": t.status,
        "progress": t.progress,
        "input": t.input,
        "output": t.output,
        "pending_confirm": t.pending_confirm,
        "error": error,
        "last_event_seq": getattr(t, "last_event_seq", 0),
        "recovery_attempts": getattr(t, "recovery_attempts", 0),
        "started_at": _dt(getattr(t, "started_at", None)),
        "created_at": _dt(t.created_at),
        "updated_at": _dt(t.updated_at),
    }


def serialize_active_task(t: Task) -> dict[str, Any]:
    """Return the owner-scoped task summary used to cold-attach a conversation.

    The full task input may contain the user's message, attachment IDs and file
    references; none of it is needed to discover an existing run in the UI.
    """
    full = serialize_task(t)
    return {
        key: full[key]
        for key in (
            "id",
            "status",
            "last_event_seq",
            "started_at",
            "updated_at",
            "pending_confirm",
            "error",
        )
    }


