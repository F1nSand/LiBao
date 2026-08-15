"""记忆路由（docs 03 §5.7）。轨迹只读分页；长期记忆 CRUD（版本只增/软删）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.api.schemas.memory import CreateLongTermMemoryRequest
from app.services.memory import MemoryService
from app.services.serializers import serialize_longterm
from app.storage.models.user import User

router = APIRouter()


@router.get("/memory/traces")
async def list_traces(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conversation_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await MemoryService().list_traces(db, user.id, page, page_size, conversation_id))


@router.get("/memory/longterm")
async def list_longterm(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cards = await MemoryService().list_cards(db, user.id)
    return ok([serialize_longterm(c) for c in cards])


@router.post("/memory/longterm")
async def create_longterm(
    req: CreateLongTermMemoryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    card = await MemoryService().create_card(
        db, user.id, req.card_type, title=req.title, body=req.body, tags=req.tags
    )
    return ok(serialize_longterm(card))


@router.get("/memory/longterm/{card_id}/versions")
async def list_versions(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await MemoryService().list_versions(db, user.id, card_id))


@router.delete("/memory/longterm/{card_id}")
async def delete_longterm(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await MemoryService().soft_delete(db, user.id, card_id)
    return ok()
