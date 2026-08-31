from __future__ import annotations

import uuid

import pytest

from app.api.routers.chat import _resolve_workspace_id
from app.core.errors import AppError
from app.storage.models.conversation import Conversation


def _conversation(workspace_id: uuid.UUID | None = None) -> Conversation:
    return Conversation(user_id=uuid.uuid4(), agent_id=uuid.uuid4(), workspace_id=workspace_id)


def test_existing_session_conversation_rejects_workspace_override():
    requested_workspace = uuid.uuid4()

    with pytest.raises(AppError) as exc:
        _resolve_workspace_id(_conversation(), requested_workspace)

    assert exc.value.code == 40909


def test_existing_workspace_conversation_rejects_different_workspace():
    bound_workspace = uuid.uuid4()

    with pytest.raises(AppError) as exc:
        _resolve_workspace_id(_conversation(bound_workspace), uuid.uuid4())

    assert exc.value.code == 40909


def test_new_workspace_conversation_keeps_persisted_workspace_id():
    bound_workspace = uuid.uuid4()
    conversation = _conversation(bound_workspace)

    assert _resolve_workspace_id(conversation, bound_workspace) == bound_workspace
