from __future__ import annotations

import uuid

import pytest

from app.checkpoints.models import ConversationCursor
from app.storage.models.message import Message
from app.storage.repositories.message import MessageRepository


def _messages(conversation_id: uuid.UUID) -> list[Message]:
    first = Message(
        conversation_id=conversation_id,
        role="user",
        content="first",
        history_parent_id=None,
    )
    second = Message(
        conversation_id=conversation_id,
        role="assistant",
        content="second",
        history_parent_id=first.id,
    )
    return [first, second]


@pytest.mark.asyncio
async def test_initialized_null_head_returns_empty_active_messages_and_count(monkeypatch):
    conversation_id = uuid.uuid4()
    rows = _messages(conversation_id)
    repo = MessageRepository()

    async def fake_list(*_args, **_kwargs):
        return [row.to_dict() for row in rows]

    monkeypatch.setattr(repo.store, "jsonl_list", fake_list)

    active = await repo.list_active(conversation_id, None, cursor_initialized=True, limit=None, offset=0)
    count = await repo.count_active(conversation_id, None, cursor_initialized=True)

    assert active == []
    assert count == 0


@pytest.mark.asyncio
async def test_uninitialized_null_head_keeps_legacy_append_only_fallback(monkeypatch):
    conversation_id = uuid.uuid4()
    rows = _messages(conversation_id)
    repo = MessageRepository()

    async def fake_list(*_args, **_kwargs):
        return [row.to_dict() for row in rows]

    monkeypatch.setattr(repo.store, "jsonl_list", fake_list)

    active = await repo.list_active(conversation_id, None, cursor_initialized=False, limit=None, offset=0)

    assert [row.content for row in active] == ["first", "second"]


def test_conversation_cursor_round_trip_preserves_initialized_empty_head():
    cursor = ConversationCursor(
        active_message_head_id=None,
        active_graph_checkpoint_id=None,
        active_code_node_id=None,
        history_revision=4,
        message_cursor_initialized=True,
    )

    restored = ConversationCursor.from_dict(cursor.to_dict())

    assert restored.active_message_head_id is None
    assert restored.message_cursor_initialized is True
    assert restored.history_revision == 4
