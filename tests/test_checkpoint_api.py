from __future__ import annotations

import uuid

import pytest

from app.api.routers import checkpoints
from app.api.schemas.checkpoints import RestorePreviewRequest
from app.storage.models.conversation import Conversation
from app.storage.models.user import User


@pytest.mark.asyncio
async def test_conversation_only_preview_succeeds_when_workspace_is_missing(monkeypatch):
    conversation = Conversation(user_id=uuid.uuid4(), agent_id=uuid.uuid4())
    user = User(
        username=f"checkpoint_api_{uuid.uuid4().hex[:8]}",
        password_hash="hashed",
        name="Checkpoint API",
        role="admin",
        org_id=uuid.UUID(int=0),
    )

    async def get_owned(self, db, conversation_id, user_id):
        return conversation

    async def workspace_must_not_be_resolved(*args, **kwargs):
        raise AssertionError("conversation_only must not resolve a workspace")

    class FakeRestoreService:
        async def preview_checkpoint(self, db, conversation, **kwargs):
            assert kwargs["mode"] == "conversation_only"
            assert kwargs["workspace_root"] is None
            assert kwargs["workspace_id"] is None
            return {"files": [], "mode": "conversation_only"}

    monkeypatch.setattr(checkpoints.ConversationService, "get_owned", get_owned)
    monkeypatch.setattr(checkpoints, "_workspace_context", workspace_must_not_be_resolved)
    monkeypatch.setattr(checkpoints, "CheckpointRestoreService", FakeRestoreService)

    response = await checkpoints.create_restore_preview(
        conversation.id,
        RestorePreviewRequest(target_checkpoint_id=uuid.uuid4(), mode="conversation_only"),
        user=user,
        db=object(),
    )

    assert response["data"]["files"] == []
