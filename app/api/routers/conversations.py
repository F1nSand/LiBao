"""会话路由（docs 03 §5.2）。全部 owner 过滤；越权 → 40401。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.api.schemas.conversations import CreateConversationRequest
from app.services.agent import AgentService
from app.services.conversation import ConversationService
from app.services.serializers import serialize_active_task, serialize_conversation
from app.services.task import TaskService
from app.storage.models.user import User

router = APIRouter()


@router.get("/conversations")
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    workspace_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    data = await ConversationService().list(db, user.id, page, page_size, workspace_id=workspace_id)
    return ok(data)


@router.post("/conversations")
async def create_conversation(
    req: CreateConversationRequest,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    agent = await AgentService().get_default(db, user.org_id)
    conv = await ConversationService().create(db, user, agent, req.title, workspace_id=req.workspace_id)
    return ok(serialize_conversation(conv))


@router.get("/conversations/{conversation_id}/active-task")
async def get_active_task(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    """Return the owner-scoped task needed to reconnect a conversation after refresh."""
    await ConversationService().get_owned(db, conversation_id, user.id)
    task, relation = await TaskService().get_current_for_conversation(db, user.id, conversation_id)
    return ok(
        {
            "conversation_id": str(conversation_id),
            "relation": relation,
            "task": serialize_active_task(task) if task is not None else None,
        }
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    conv = await ConversationService().get_owned(db, conversation_id, user.id)
    return ok(serialize_conversation(conv))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    conv = await ConversationService().get_owned(db, conversation_id, user.id)
    await ConversationService().delete(db, conv)
    return ok()


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    conv = await ConversationService().get_owned(db, conversation_id, user.id)
    data = await ConversationService().messages(db, conv, page, page_size)
    return ok(data)


@router.get("/conversations/{conversation_id}/trajectory")
async def get_conversation_trajectory(
    conversation_id: uuid.UUID,
    before_seq: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    conv = await ConversationService().get_owned(db, conversation_id, user.id)
    return ok(await ConversationService().trajectory(db, conv, before_seq, limit))
