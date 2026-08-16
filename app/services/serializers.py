"""ORM → API 契约 dict（docs 03 §5 / FrontEnd types，字段 snake_case）。"""
from __future__ import annotations

from typing import Any

from app.storage.models.agent import AgentConfig, AgentVersion
from app.storage.models.attachment import Attachment
from app.storage.models.conversation import Conversation
from app.storage.models.kb import KbCollection, KbDocument
from app.storage.models.mcp_server import McpServer
from app.storage.models.memory import LongTermMemory, LongTermMemoryVersion, MemoryTrace
from app.storage.models.message import Message
from app.storage.models.task import Task
from app.storage.models.tool_definition import ToolDefinition
from app.storage.models.user import User
from app.tools.registry import get_by_name


def _dt(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "name": user.name,
        "username": user.username,
        "role": user.role,
        "org_id": str(user.org_id),
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
        "last_message_at": _dt(conv.last_message_at),
        "created_at": _dt(conv.created_at),
    }


def serialize_message(msg: Message) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "role": msg.role,
        "content": msg.content,
        "attachments": msg.attachments or [],
        "tool_calls": msg.tool_calls or [],
        "token_usage": msg.token_usage,
        "trace_id": msg.trace_id,
        "created_at": _dt(msg.created_at),
    }


def serialize_agent(agent: AgentConfig) -> dict[str, Any]:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "model": agent.model,
        "system_prompt": agent.system_prompt,
        "graph_template": agent.graph_template,
        "skills": agent.skills or [],
        "tools": agent.tools or [],
        "max_steps": agent.max_steps,
        "status": agent.status,
        "current_version": agent.current_version,
        "created_at": _dt(agent.created_at),
        "updated_at": _dt(agent.updated_at),
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
        "created_at": _dt(t.created_at),
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


def serialize_memory_trace(t: MemoryTrace) -> dict[str, Any]:
    """轨迹序列化（docs 03 §5.7 / FrontEnd MemoryTrace）。summary 字段对齐前端（取 content）。"""
    return {
        "id": str(t.id),
        "conversation_id": str(t.conversation_id) if t.conversation_id else None,
        "summary": t.content,
        "role": t.role,
        "created_at": _dt(t.created_at),
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


def serialize_task(t: Task) -> dict[str, Any]:
    """任务序列化（docs 03 §5.3）。error 序列化为 message 字符串（前端 Task.error?: string）。"""
    return {
        "id": str(t.id),
        "agent_id": str(t.agent_id),
        "status": t.status,
        "progress": t.progress,
        "input": t.input,
        "output": t.output,
        "pending_confirm": t.pending_confirm,
        "error": (t.error or {}).get("message") if t.error else None,
        "created_at": _dt(t.created_at),
        "updated_at": _dt(t.updated_at),
    }


def serialize_agent_version(
    ver: AgentVersion, name: str = "", graph_template: str = "single", max_steps: int = 50
) -> dict[str, Any]:
    """版本序列化（docs 03 §5.4）。版本快照不含 graph_template/max_steps（04 §3.4），
    用当前 agent 的真实值填充（F9：避免硬编码误导）。"""
    return {
        "id": str(ver.id),
        "agent_id": str(ver.agent_id),
        "version": ver.version,
        "config": {
            "name": name,
            "model": ver.model,
            "system_prompt": ver.system_prompt,
            "skills": ver.skills or [],
            "tools": ver.tools or [],
            "graph_template": graph_template,
            "max_steps": max_steps,
        },
        "prefix_hash": ver.prefix_hash,
        "created_at": _dt(ver.created_at),
    }
