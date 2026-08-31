from __future__ import annotations

import hashlib
import uuid

import pytest

from app.checkpoints.models import FileAfterState, FileMutationRecord
from app.checkpoints.service import CheckpointService
from app.checkpoints.store import CodeCheckpointStore


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@pytest.mark.asyncio
async def test_write_then_delete_in_same_checkpoint_records_final_nonexistence(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    checkpoint = await CheckpointService(store).create_anchor(
        conversation_id=uuid.uuid4(),
        user_message_id=uuid.uuid4(),
        workspace_identity="workspace",
        anchor_message_head_id=None,
    )
    conversation_id = checkpoint.conversation_id

    await store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"before",
        tool_call_id="write",
        planned_after_sha256=_sha(b"after"),
        planned_after_exists=True,
    )
    await store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=_sha(b"after"),
        final_after_exists=True,
    )
    await store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"after",
        tool_call_id="delete",
        planned_after_sha256=None,
        planned_after_exists=False,
    )
    await store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=None,
        final_after_exists=False,
    )

    loaded = await store.read_checkpoint(conversation_id, checkpoint.id)
    assert loaded is not None
    mutation = loaded.files["note.txt"]
    assert mutation.before.exists is True
    assert mutation.planned_after == FileAfterState(False, None)
    assert mutation.final_after == FileAfterState(False, None)
    assert mutation.final_after_recorded is True


@pytest.mark.asyncio
async def test_new_file_then_delete_is_not_false_restore_conflict(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    service = CheckpointService(store)
    conversation_id = uuid.uuid4()
    checkpoint = await service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity=f"session:{tmp_path / 'workspace'}",
        anchor_message_head_id=None,
    )
    await store.prepare_missing_file(
        conversation_id,
        checkpoint.id,
        "new.txt",
        tool_call_id="write",
        planned_after_sha256=_sha(b"new"),
        planned_after_exists=True,
    )
    await store.finalize_file(
        conversation_id,
        checkpoint.id,
        "new.txt",
        final_after_sha256=_sha(b"new"),
        final_after_exists=True,
    )
    await store.prepare_file(
        conversation_id,
        checkpoint.id,
        "new.txt",
        b"new",
        tool_call_id="delete",
        planned_after_sha256=None,
        planned_after_exists=False,
    )
    await store.finalize_file(
        conversation_id,
        checkpoint.id,
        "new.txt",
        final_after_sha256=None,
        final_after_exists=False,
    )
    loaded = await store.read_checkpoint(conversation_id, checkpoint.id)
    assert loaded is not None
    mutation = loaded.files["new.txt"]
    assert mutation.before.exists is False
    assert mutation.final_after_recorded is True
    assert mutation.final_after is not None and mutation.final_after.exists is False


@pytest.mark.asyncio
async def test_delete_then_recreate_records_latest_final_bytes(tmp_path):
    store = CodeCheckpointStore(tmp_path / ".agent")
    service = CheckpointService(store)
    conversation_id = uuid.uuid4()
    checkpoint = await service.create_anchor(
        conversation_id=conversation_id,
        user_message_id=uuid.uuid4(),
        workspace_identity="workspace",
        anchor_message_head_id=None,
    )
    await store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"old",
        tool_call_id="delete",
        planned_after_sha256=None,
        planned_after_exists=False,
    )
    await store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=None,
        final_after_exists=False,
    )
    await store.prepare_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        b"new",
        tool_call_id="recreate",
        planned_after_sha256=_sha(b"new"),
        planned_after_exists=True,
    )
    await store.finalize_file(
        conversation_id,
        checkpoint.id,
        "note.txt",
        final_after_sha256=_sha(b"new"),
        final_after_exists=True,
    )
    loaded = await store.read_checkpoint(conversation_id, checkpoint.id)
    assert loaded is not None
    mutation = loaded.files["note.txt"]
    assert mutation.before.blob_sha256 == _sha(b"old")
    assert mutation.final_after == FileAfterState(True, _sha(b"new"))


def test_v1_null_final_hash_distinguishes_unfinalized_and_deleted():
    base = {
        "path": "note.txt",
        "before": {"exists": True, "blob_sha256": _sha(b"old"), "size_bytes": 3, "content_kind": "text"},
        "planned_after_sha256": None,
        "final_after_sha256": None,
        "tool_call_ids": [],
    }
    prepared = FileMutationRecord.from_dict({**base, "status": "prepared"})
    applied = FileMutationRecord.from_dict({**base, "status": "applied"})

    assert prepared.final_after_recorded is False
    assert prepared.final_after is None
    assert prepared.planned_after == FileAfterState(False, None)
    assert applied.final_after_recorded is True
    assert applied.final_after == FileAfterState(False, None)
