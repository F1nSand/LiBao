"""Agent 路由（docs 03 §5.4）。M1 只读；创建/版本化/发布为 M2 接缝。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.services.agent import AgentService
from app.services.serializers import serialize_agent
from app.storage.models.user import User

router = APIRouter()


@router.get("/agents")
async def list_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await AgentService().list_for_org(db, user.org_id, page, page_size)
    return ok(data)


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await AgentService().get_in_org(db, agent_id, user.org_id)
    return ok(serialize_agent(agent))


@router.get("/agents/{agent_id}/versions")
async def get_agent_versions(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await AgentService().get_in_org(db, agent_id, user.org_id)
    versions = await AgentService().versions(db, agent_id)
    return ok(versions)
