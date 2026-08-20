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
from app.services.attachment import AttachmentService
from app.services.conversation import ConversationService
from app.services.workspace import WorkspaceService
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
    # 单通用 Agent：所有会话固定用组织默认通用 Agent（不接收 agent_id）
    agent = await AgentService().get_default(db, user.org_id)
    if req.conversation_id is None:
        conversation = await conv_service.create(db, user, agent, "新会话", workspace_id=req.workspace_id)
    else:
        conversation = await conv_service.get_owned(db, req.conversation_id, user.id)

    # M7-B：解析工作区（会话优先，其次请求）→ 项目级 agent + 文件工具
    workspace = None
    ws_id = conversation.workspace_id or req.workspace_id
    if ws_id is not None:
        ws = await WorkspaceService().get_in_org(db, user.org_id, str(ws_id))
        workspace = {"id": str(ws.id), "root_path": ws.root_path, "system_prompt_fragment": ws.system_prompt_fragment}

    graph = request.app.state.graph
    trace_id = get_trace_id()

    # M3：附件校验（每个必须是当前用户有效附件，否则 40403）→ 透传编排落库
    att_service = AttachmentService()
    attachments: list[str] = []
    for aid in req.message.attachments or []:  # aid 已由 schema 校验为 uuid.UUID
        att = await att_service.get_attachment(db, user, aid)
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
            workspace=workspace,
            trace_id=trace_id,
        ),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
