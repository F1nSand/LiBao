"""对话流式路由（docs 03 §5.2 ★ M1 核心端点 POST /chat/stream）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user, get_db
from app.api.schemas.chat import ChatRequest
from app.core.config import get_settings
from app.core.errors import ERR_WORKSPACE_FILE_REF_INVALID, AppError
from app.core.logging import get_trace_id
from app.orchestration.chat_stream import chat_stream_events
from app.services.agent import AgentService
from app.services.attachment import AttachmentService
from app.services.conversation import ConversationService
from app.services.skill import discover_workspace_agent
from app.services.workspace import WorkspaceService
from app.storage.models.user import User

router = APIRouter()


def _session_workspace(conv_id: str) -> dict[str, Any]:
    """非工作区对话 → 临时会话工作区（~/.LiBao/cache/sessions/<conv_id>/，2026-08-25 方案 A）。

    让普通对话的 agent 也能落地生成文件（docx 等）；root_path 指向可 TTL 清理的缓存目录。
    overlay 字段留空（不注入 [工作区]/[项目约定]/skills），只提供文件工具 + 落地根。
    """
    root = Path(get_settings().cache_dir) / "sessions" / conv_id
    root.mkdir(parents=True, exist_ok=True)
    return {
        "id": None,
        "root_path": str(root),
        "project_instructions": "",
        "skills": [],
        "agent_md": "",
        "memory": [],
        "knowledge": [],
    }


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    conv_service = ConversationService()
    # 单通用 Agent：所有会话固定用组织默认通用 Agent（不接收 agent_id）
    agent = await AgentService().get_default(db, user.org_id)
    if req.conversation_id is None:
        conversation = await conv_service.create(db, user, agent, "新会话", workspace_id=req.workspace_id)
    else:
        conversation = await conv_service.get_owned(db, req.conversation_id, user.id)

    # M7-B：解析工作区（会话优先，其次请求）→ 项目级 agent + 文件工具；
    # 非工作区对话 → 隐式临时会话工作区（方案 A：普通对话也能生成文件，落地 cache/sessions/<conv_id>/）
    workspace = None
    ws_id = conversation.workspace_id or req.workspace_id
    if ws_id is not None:
        ws = await WorkspaceService().get_in_org(db, user.org_id, str(ws_id))
        overlay = discover_workspace_agent(ws.root_path)  # 工作区 `.agent/` 项目级能力叠加
        workspace = {
            "id": str(ws.id),
            "root_path": ws.root_path,
            "project_instructions": ws.project_instructions,
            "skills": overlay["skills"],
            "agent_md": overlay["agent_md"],
            "memory": overlay["memory"],
            "knowledge": overlay["knowledge"],
        }
    else:
        workspace = _session_workspace(str(conversation.id))

    # 工作区引用只能绑定真实的 workspace root。普通会话使用的临时会话目录
    # 仅供工具落地，不接受客户端借此读取任意路径。
    file_refs: list[str] = []
    if req.message.file_refs:
        if ws_id is None:
            raise AppError(ERR_WORKSPACE_FILE_REF_INVALID, "工作区文件引用非法或不可读取")
        file_refs = await WorkspaceService().validate_file_refs(
            db, user, str(ws_id), [ref.path for ref in req.message.file_refs]
        )

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
            file_refs=file_refs,
            workspace=workspace,
            trace_id=trace_id,
        ),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
