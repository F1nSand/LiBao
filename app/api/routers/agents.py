"""Agent 路由（docs 03 §5.4）。M2：读写 + 版本化 + 发布/下线 + 试跑 invoke。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.api.schemas.agents import AgentWriteRequest
from app.api.schemas.chat import ChatRequest
from app.core.logging import get_trace_id
from app.orchestration.chat_stream import agent_invoke_events
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


@router.post("/agents")
async def create_agent(
    req: AgentWriteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await AgentService().create(db, user.org_id, req)
    return ok(serialize_agent(agent))


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await AgentService().get_in_org(db, agent_id, user.org_id)
    return ok(serialize_agent(agent))


@router.put("/agents/{agent_id}")
async def update_agent(
    agent_id: uuid.UUID,
    req: AgentWriteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await AgentService().get_in_org(db, agent_id, user.org_id)
    agent = await AgentService().update(db, agent, req)
    return ok(serialize_agent(agent))


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await AgentService().get_in_org(db, agent_id, user.org_id)
    await AgentService().soft_delete(db, agent)
    return ok()


@router.get("/agents/{agent_id}/versions")
async def get_agent_versions(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await AgentService().get_in_org(db, agent_id, user.org_id)
    versions = await AgentService().versions(db, agent)
    return ok(versions)


@router.post("/agents/{agent_id}/publish")
async def publish_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await AgentService().get_in_org(db, agent_id, user.org_id)
    agent = await AgentService().publish(db, agent)
    return ok(serialize_agent(agent))


@router.post("/agents/{agent_id}/unpublish")
async def unpublish_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await AgentService().get_in_org(db, agent_id, user.org_id)
    agent = await AgentService().unpublish(db, agent)
    return ok(serialize_agent(agent))


@router.post("/agents/{agent_id}/invoke")
async def invoke_agent(
    agent_id: uuid.UUID,
    req: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = await AgentService().get_in_org(db, agent_id, user.org_id)
    return StreamingResponse(
        agent_invoke_events(
            db=db,
            graph=request.app.state.graph,
            agent=agent,
            user=user,
            content=req.message.content,
            trace_id=get_trace_id(),
        ),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
