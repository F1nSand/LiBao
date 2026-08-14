"""ORM → API 契约 dict（docs 03 §5 / FrontEnd types，字段 snake_case）。"""
from __future__ import annotations

from typing import Any

from app.storage.models.agent import AgentConfig, AgentVersion
from app.storage.models.conversation import Conversation
from app.storage.models.message import Message
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


def serialize_agent_version(ver: AgentVersion) -> dict[str, Any]:
    return {
        "id": str(ver.id),
        "agent_id": str(ver.agent_id),
        "version": ver.version,
        "config": {
            "name": "",
            "model": ver.model,
            "system_prompt": ver.system_prompt,
            "skills": ver.skills or [],
            "tools": ver.tools or [],
            "graph_template": "single",
            "max_steps": 50,
        },
        "prefix_hash": ver.prefix_hash,
        "created_at": _dt(ver.created_at),
    }
