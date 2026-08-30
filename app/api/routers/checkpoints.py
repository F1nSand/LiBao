"""消息级 checkpoint 浏览、diff preview 与确认恢复接口。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.api.routers.chat import _session_workspace
from app.api.schemas.checkpoints import RestoreExecuteRequest, RestorePreviewRequest
from app.checkpoints.restore import CheckpointRestoreService
from app.services.conversation import ConversationService
from app.services.workspace import WorkspaceService
from app.storage.models.user import User

router = APIRouter()


async def _workspace_context(db: Any, user: User, conversation: Any) -> tuple[str, str | None]:
    if conversation.workspace_id:
        workspace = await WorkspaceService().get_in_org(db, user.org_id, str(conversation.workspace_id))
        return workspace.root_path, str(workspace.id)
    context = _session_workspace(str(conversation.id))
    return context["root_path"], None


@router.get("/conversations/{conversation_id}/checkpoints")
async def list_checkpoints(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    conversation = await ConversationService().get_owned(db, conversation_id, user.id)
    service = CheckpointRestoreService()
    checkpoints = await service.checkpoints.store.list_checkpoints(conversation.id)
    operations = await service.checkpoints.store.list_operations(conversation.id)
    return ok(
        {
            "conversation_id": str(conversation.id),
            "current_state_id": str(conversation.active_code_node_id) if conversation.active_code_node_id else None,
            "cursor": {
                "active_message_head_id": (
                    str(conversation.active_message_head_id) if conversation.active_message_head_id else None
                ),
                "active_graph_checkpoint_id": conversation.active_graph_checkpoint_id,
                "active_code_node_id": str(conversation.active_code_node_id)
                if conversation.active_code_node_id
                else None,
                "history_revision": conversation.history_revision,
            },
            "items": [
                {
                    "kind": "checkpoint",
                    "id": str(item.id),
                    "user_message_id": str(item.user_message_id),
                    "status": item.status,
                    "changed_file_count": len(item.files),
                    "created_at": item.created_at.isoformat(),
                }
                for item in checkpoints
            ]
            + [
                {
                    "kind": "rollback_operation",
                    "id": str(item.id),
                    "target_checkpoint_id": str(item.target_checkpoint_id),
                    "mode": item.mode,
                    "status": item.status,
                    "created_at": item.created_at.isoformat(),
                }
                for item in operations
            ],
        }
    )


@router.post("/conversations/{conversation_id}/restore-previews")
async def create_restore_preview(
    conversation_id: uuid.UUID,
    req: RestorePreviewRequest,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    conversation = await ConversationService().get_owned(db, conversation_id, user.id)
    target_id = req.target_checkpoint_id or req.target_id
    if target_id is None:
        from app.core.errors import AppError

        raise AppError(40031, "必须提供 target_checkpoint_id 或 target_id")
    root, workspace_id = await _workspace_context(db, user, conversation)
    if req.target_type == "rollback_operation_before":
        return ok(
            await CheckpointRestoreService().preview_operation_before(
                db, conversation, target_id, root
            )
        )
    return ok(
        await CheckpointRestoreService().preview_checkpoint(
            db,
            conversation,
            target_checkpoint_id=target_id,
            mode=req.mode,
            workspace_root=root,
            workspace_id=workspace_id,
        )
    )


@router.post("/conversations/{conversation_id}/restores")
async def execute_restore(
    conversation_id: uuid.UUID,
    req: RestoreExecuteRequest,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    conversation = await ConversationService().get_owned(db, conversation_id, user.id)
    return ok(await CheckpointRestoreService().execute_preview(db, conversation, req.preview_id))
