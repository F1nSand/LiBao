"""对话流式路由（docs 03 §5.2 ★ M1 核心端点 POST /chat/stream）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas.chat import ChatRequest
from app.core.logging import get_trace_id
from app.orchestration.chat_stream import chat_stream_events
from app.services.agent import AgentService
from app.services.attachment import AttachmentService
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
    # 先校验 agent（published + 同 org），避免越权请求在后续失败前残留孤儿会话
    agent = await AgentService().get_published(db, req.agent_id, user.org_id)
    if req.conversation_id is None:
        conversation = await conv_service.create(db, user, agent, "新会话")
    else:
        conversation = await conv_service.get_owned(db, req.conversation_id, user.id)

    graph = request.app.state.graph
    trace_id = get_trace_id()

    # M3：附件校验（每个必须是当前用户有效附件，否则 40403）→ 透传编排落库
    att_service = AttachmentService()
    attachments: list[str] = []
    for aid in req.message.attachments or []:
        att = await att_service.get_attachment(db, user, uuid.UUID(aid))
        attachments.append(str(att.id))

    return StreamingResponse(
        chat_stream_events(
            db=db,
            graph=graph,
            conversation=conversation,
            agent=agent,
            user=user,
            content=req.message.content,
            attachments=attachments,
            trace_id=trace_id,
        ),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
