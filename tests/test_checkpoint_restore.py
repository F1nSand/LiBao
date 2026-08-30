from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from app.checkpoints.restore import CheckpointRestoreService
from app.checkpoints.service import CheckpointService
from app.checkpoints.store import CodeCheckpointStore
from app.storage.models.conversation import Conversation


class _Db:
    async def commit(self) -> None:
        return None


def _conversation(conversation_id: uuid.UUID) -> Conversation:
    return Conversation(user_id=uuid.uuid4(), agent_id=uuid.uuid4(), id=conversation_id)


@pytest.mark.asyncio
async def test_preview_and_execute_restores_bytes(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        workspace_identity=f"session:{tmp_path / 'workspace'}",
        anchor_message_head_id=None,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    target.write_bytes(b"before\n")
    await checkpoint_store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"before\n",
        tool_call_id="call",
        planned_after_sha256=hashlib.sha256(b"after\n").hexdigest(),
    )
    target.write_bytes(b"after\n")
    await checkpoint_store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=hashlib.sha256(b"after\n").hexdigest(),
    )

    conversation = _conversation(conversation_id)
    service = CheckpointRestoreService(checkpoint_service)
    preview = await service.preview_checkpoint(
        _Db(),
        conversation,
        target_checkpoint_id=checkpoint.id,
        mode="code_only",
        workspace_root=str(workspace),
    )
    assert preview["files"][0]["diff"]
    result = await service.execute_preview(_Db(), conversation, uuid.UUID(preview["preview_id"]))

    assert result["status"] == "completed"
    assert target.read_bytes() == b"before\n"
    assert len(await checkpoint_store.list_operations(conversation_id)) == 1


@pytest.mark.asyncio
async def test_manual_conflict_is_skipped(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity=f"session:{tmp_path / 'workspace'}",
        anchor_message_head_id=None,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    target.write_text("before", encoding="utf-8")
    await checkpoint_store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"before",
        tool_call_id="call",
        planned_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    target.write_text("after", encoding="utf-8")
    await checkpoint_store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=hashlib.sha256(b"after").hexdigest(),
    )
    target.write_text("manual edit", encoding="utf-8")

    service = CheckpointRestoreService(checkpoint_service)
    preview = await service.preview_checkpoint(
        _Db(),
        _conversation(conversation_id),
        target_checkpoint_id=checkpoint.id,
        mode="both",
        workspace_root=str(workspace),
    )
    result = await service.execute_preview(_Db(), _conversation(conversation_id), uuid.UUID(preview["preview_id"]))

    assert result["status"] == "partial"
    assert result["skipped_conflicts"] == ["note.txt"]
    assert target.read_text(encoding="utf-8") == "manual edit"
