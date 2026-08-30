from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from app.checkpoints.restore import CheckpointRestoreService
from app.checkpoints.service import CheckpointService
from app.checkpoints.store import CodeCheckpointStore
from app.core.errors import AppError
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
    conversation = _conversation(conversation_id)
    preview = await service.preview_checkpoint(
        _Db(),
        conversation,
        target_checkpoint_id=checkpoint.id,
        mode="both",
        workspace_root=str(workspace),
    )
    result = await service.execute_preview(_Db(), _conversation(conversation_id), uuid.UUID(preview["preview_id"]))

    assert result["status"] == "partial"
    assert result["skipped_conflicts"] == ["note.txt"]
    assert target.read_text(encoding="utf-8") == "manual edit"


@pytest.mark.asyncio
async def test_rollback_can_switch_back_to_a_later_checkpoint(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"

    async def mutate_before_turn(before: bytes, after: bytes) -> object:
        target.write_bytes(before)
        checkpoint = await checkpoint_service.create_anchor(
            conversation_id=conversation_id,
            user_message_id=uuid.uuid4(),
            workspace_identity=f"session:{workspace}",
            anchor_message_head_id=None,
        )
        await checkpoint_store.prepare_file(
            conversation_id,
            checkpoint.id,
            "note.txt",
            before,
            tool_call_id=str(uuid.uuid4()),
            planned_after_sha256=hashlib.sha256(after).hexdigest(),
        )
        target.write_bytes(after)
        await checkpoint_store.finalize_file(
            conversation_id,
            checkpoint.id,
            "note.txt",
            final_after_sha256=hashlib.sha256(after).hexdigest(),
        )
        return checkpoint

    await mutate_before_turn(b"a", b"b")
    checkpoint_b = await mutate_before_turn(b"b", b"c")
    checkpoint_c = await mutate_before_turn(b"c", b"d")

    service = CheckpointRestoreService(checkpoint_service)
    conversation = _conversation(conversation_id)
    first_preview = await service.preview_checkpoint(
        _Db(), conversation, target_checkpoint_id=checkpoint_b.id, mode="code_only", workspace_root=str(workspace)
    )
    await service.execute_preview(_Db(), conversation, uuid.UUID(first_preview["preview_id"]))
    assert target.read_bytes() == b"b"

    second_preview = await service.preview_checkpoint(
        _Db(), conversation, target_checkpoint_id=checkpoint_c.id, mode="code_only", workspace_root=str(workspace)
    )
    assert second_preview["files"][0]["conflict"] is False
    await service.execute_preview(_Db(), conversation, uuid.UUID(second_preview["preview_id"]))
    assert target.read_bytes() == b"c"


@pytest.mark.asyncio
async def test_conversation_only_preview_ignores_workspace_identity_mismatch(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity="foreign:/a/different/root",
        anchor_message_head_id=None,
    )

    service = CheckpointRestoreService(checkpoint_service)
    conversation = _conversation(conversation_id)
    preview = await service.preview_checkpoint(
        _Db(),
        conversation,
        target_checkpoint_id=checkpoint.id,
        mode="conversation_only",
        workspace_root=None,
    )

    assert preview["files"] == []
    result = await service.execute_preview(_Db(), conversation, uuid.UUID(preview["preview_id"]))
    assert result["status"] == "completed"
    assert result["restored_files"] == 0


@pytest.mark.asyncio
async def test_code_modes_still_reject_workspace_identity_mismatch(tmp_path: Path):
    checkpoint_store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint_service = CheckpointService(checkpoint_store)
    conversation_id = uuid.uuid4()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    checkpoint = await checkpoint_service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity=f"session:{tmp_path / 'other'}",
        anchor_message_head_id=None,
    )
    service = CheckpointRestoreService(checkpoint_service)

    for mode in ("code_only", "both"):
        with pytest.raises(AppError) as exc:
            await service.preview_checkpoint(
                _Db(),
                _conversation(conversation_id),
                target_checkpoint_id=checkpoint.id,
                mode=mode,
                workspace_root=str(workspace),
            )
        assert exc.value.code == 40932
