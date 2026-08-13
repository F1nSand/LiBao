"""对话流式路由（docs 03 §5.2 ★ M1 核心端点 POST /chat/stream）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas.chat import ChatRequest
from app.core.logging import get_trace_id
from app.orchestration.chat_stream import chat_stream_events
from app.services.agent import AgentService
from app.services.conversation import ConversationService
from app.storage.models.user import User

router = APIRouter()


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv_service = ConversationService()
    if req.conversation_id is None:
        # conversation_id 为空 → 新建会话
        conversation = await conv_service.create(db, user, req.agent_id, "新会话")
    else:
        conversation = await conv_service.get_owned(db, req.conversation_id, user.id)

    agent = await AgentService().get_published(db, req.agent_id, user.org_id)
    graph = request.app.state.graph
    trace_id = get_trace_id()

    return StreamingResponse(
        chat_stream_events(
            db=db,
            graph=graph,
            conversation=conversation,
            agent=agent,
            user=user,
            content=req.message.content,
            trace_id=trace_id,
        ),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
