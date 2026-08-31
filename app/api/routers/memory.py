"""记忆路由（《02》接口契约 §5.7）。长期记忆 CRUD（版本只增/软删）+ maintenance（读最近 messages）+
P5：项目记忆文件列表（GET /memory/project，工作区 .agent/memory/*.md 索引）+ update 端点。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.api.schemas.memory import CreateLongTermMemoryRequest, UpdateLongTermMemoryRequest
from app.services.memory import MemoryService, run_maintenance
from app.services.serializers import serialize_longterm
from app.services.workspace import WorkspaceService
from app.storage.models.user import User

router = APIRouter()


@router.get("/memory/longterm")
async def list_longterm(
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    cards = await MemoryService().list_cards(db, user.id)
    return ok([serialize_longterm(c) for c in cards])


@router.post("/memory/longterm")
async def create_longterm(
    req: CreateLongTermMemoryRequest,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    card = await MemoryService().create_card(
        db,
        user.id,
        req.card_type,
        title=req.title,
        body=req.body,
        tags=req.tags,
        importance=req.importance or 0.0,
        workspace_id=uuid.UUID(req.workspace_id) if req.workspace_id else None,
    )
    return ok(serialize_longterm(card))


@router.put("/memory/longterm/{card_id}")
async def update_longterm(
    card_id: uuid.UUID,
    req: UpdateLongTermMemoryRequest,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    """改写 = 只增新版本（ADR-06）；importance 可选更新。"""
    card = await MemoryService().update_card(db, user.id, card_id, req.body, importance=req.importance)
    return ok(serialize_longterm(card))


@router.get("/memory/project")
async def list_project_memory(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    """工作区项目记忆文件列表（.agent/memory/*.md 索引；正文按需 read_file，不走 RAG）。"""
    ws = await WorkspaceService().get_in_org(db, user.org_id, workspace_id)
    files = await MemoryService().list_project_memory(ws.root_path)
    return ok(files)


@router.post("/memory/maintenance")
async def maintenance(
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    return ok(await run_maintenance(db, user.id))


@router.get("/memory/longterm/{card_id}/versions")
async def list_versions(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    return ok(await MemoryService().list_versions(db, user.id, card_id))


@router.delete("/memory/longterm/{card_id}")
async def delete_longterm(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    await MemoryService().soft_delete(db, user.id, card_id)
    return ok()
