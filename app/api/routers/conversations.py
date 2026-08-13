"""会话路由（docs 03 §5.2）。全部 owner 过滤；越权 → 40401。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.api.schemas.conversations import CreateConversationRequest
from app.services.conversation import ConversationService
from app.services.serializers import serialize_conversation
from app.storage.models.user import User

router = APIRouter()


@router.get("/conversations")
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await ConversationService().list(db, user.id, page, page_size)
    return ok(data)


@router.post("/conversations")
async def create_conversation(
    req: CreateConversationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await ConversationService().create(db, user, req.agent_id, req.title)
    return ok(serialize_conversation(conv))


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await ConversationService().get_owned(db, conversation_id, user.id)
    return ok(serialize_conversation(conv))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
):
    conv = await ConversationService().get_owned(db, conversation_id, user.id)
    data = await ConversationService().messages(db, conv, page, page_size)
    return ok(data)
