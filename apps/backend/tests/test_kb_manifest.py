import asyncio
import json
import uuid

import pytest

from app.storage.kb.manifest import KbManifestStore, ManifestCorruptError, empty_manifest, normalize_manifest
from app.storage.models.kb import KbDocument
from app.storage.repositories.kb import KbRepository


def test_empty_manifest_is_v2():
    assert empty_manifest() == {"version": 2, "documents": {}, "chunks": {}}


def test_normalize_v1_manifest_without_mutating_source():
    doc_id = str(uuid.uuid4())
    chunk = {"chunk_id": str(uuid.uuid4()), "content": "正文", "chunk_index": 0}
    raw = {"version": 1, "documents": {doc_id: {"status": "indexed", "custom": 7}}, "chunks": {doc_id: [chunk]}}

    normalized = normalize_manifest(raw)

    assert raw["chunks"][doc_id] == [chunk]
    assert normalized["version"] == 2
    assert normalized["documents"][doc_id]["active_generation"] == "legacy-v1"
    assert normalized["documents"][doc_id]["custom"] == 7
    assert normalized["chunks"][doc_id] == {"legacy-v1": [chunk]}


def test_normalize_v1_only_marks_indexed_documents_with_chunks_active():
    indexed_id, archived_id = str(uuid.uuid4()), str(uuid.uuid4())
    raw = {
        "version": 1,
        "documents": {indexed_id: {"status": "indexed"}, archived_id: {"status": "archived"}},
        "chunks": {indexed_id: [{"chunk_id": "one"}], archived_id: [{"chunk_id": "two"}]},
    }

    normalized = normalize_manifest(raw)

    assert normalized["documents"][indexed_id]["active_generation"] == "legacy-v1"
    assert normalized["documents"][archived_id]["active_generation"] is None


async def test_store_atomically_saves_and_reloads_v2_manifest(tmp_path):
    store = KbManifestStore(tmp_path)
    collection_id = uuid.uuid4()
    manifest = empty_manifest()
    document_id = str(uuid.uuid4())
    manifest["documents"][document_id] = {"status": "uploaded"}

    await store.save(collection_id, manifest)
    loaded = await store.load(collection_id)

    assert loaded["version"] == 2
    assert loaded["documents"][document_id]["status"] == "uploaded"
    assert loaded["documents"][document_id]["index_state"] == "idle"
    assert not list((tmp_path / str(collection_id)).glob("*.tmp"))


async def test_v1_roundtrip_preserves_legacy_disk_shape_until_explicit_upgrade(tmp_path):
    store = KbManifestStore(tmp_path)
    collection_id, document_id = uuid.uuid4(), str(uuid.uuid4())
    legacy = {
        "version": 1,
        "documents": {document_id: {"status": "indexed"}},
        "chunks": {document_id: [{"chunk_id": "c1"}]},
    }
    path = tmp_path / str(collection_id) / "index.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(legacy), encoding="utf-8")

    normalized = await store.load(collection_id)
    normalized["documents"][document_id]["custom"] = "kept"
    await store.save(collection_id, normalized)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert saved["chunks"][document_id] == [{"chunk_id": "c1"}]
    assert saved["documents"][document_id]["custom"] == "kept"


async def test_corrupt_primary_recovers_backup_and_marks_documents_for_repair(tmp_path):
    store = KbManifestStore(tmp_path)
    collection_id, document_id = uuid.uuid4(), str(uuid.uuid4())
    original = empty_manifest()
    original["documents"][document_id] = {"status": "indexed"}
    await store.save(collection_id, original)
    updated = empty_manifest()
    updated["documents"][document_id] = {"status": "archived"}
    await store.save(collection_id, updated)
    path = tmp_path / str(collection_id) / "index.json"
    path.write_text("{broken", encoding="utf-8")

    loaded = await store.load(collection_id)

    assert loaded["documents"][document_id]["status"] == "indexed"
    assert loaded["documents"][document_id]["index_state"] == "repair_required"
    assert loaded["repair_required"] is True


async def test_corrupt_primary_and_backup_raise_explicit_error(tmp_path):
    store = KbManifestStore(tmp_path)
    collection_id = uuid.uuid4()
    path = tmp_path / str(collection_id) / "index.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    path.with_suffix(".json.bak").write_text("also broken", encoding="utf-8")

    with pytest.raises(ManifestCorruptError):
        await store.load(collection_id)


async def test_concurrent_updates_across_store_instances_do_not_lose_writes(tmp_path):
    collection_id = uuid.uuid4()
    first, second = KbManifestStore(tmp_path), KbManifestStore(tmp_path)
    await first.save(collection_id, empty_manifest())

    await asyncio.gather(
        first.update(collection_id, lambda manifest: manifest["documents"].update({"a": {"status": "uploaded"}})),
        second.update(collection_id, lambda manifest: manifest["documents"].update({"b": {"status": "uploaded"}})),
    )

    loaded = await first.load(collection_id)
    assert set(loaded["documents"]) == {"a", "b"}


async def test_repository_uses_atomic_updates_for_legacy_manifest_rows():
    repo = KbRepository()
    collection = await repo.create_collection(uuid.UUID(int=0), "manifest-concurrency", 512, 64)

    await asyncio.gather(
        repo._update_index(collection.id, lambda index: index["documents"].update({"a": {"status": "uploaded"}})),
        repo._update_index(collection.id, lambda index: index["documents"].update({"b": {"status": "uploaded"}})),
    )

    loaded = await repo._load_index(collection.id)
    assert set(loaded["documents"]) == {"a", "b"}


async def test_repository_lists_only_the_manifest_active_generation():
    repo = KbRepository()
    collection = await repo.create_collection(uuid.UUID(int=0), "active-generation", 512, 64)
    document_id = uuid.uuid4()
    manifest = empty_manifest()
    manifest["documents"][str(document_id)] = {"status": "indexed", "active_generation": "new"}
    manifest["chunks"][str(document_id)] = {
        "old": [{"chunk_id": str(uuid.uuid4()), "chunk_index": 0, "content": "old"}],
        "new": [{"chunk_id": str(uuid.uuid4()), "chunk_index": 0, "content": "new"}],
    }
    await repo.manifests.save(collection.id, manifest, version=2)

    chunks = await repo.list_chunks(document_id)

    assert [chunk.content for chunk in chunks] == ["new"]


async def test_model_defaults_keep_old_document_json_loadable():
    document = KbDocument.from_dict(
        {
            "collection_id": str(uuid.uuid4()),
            "org_id": str(uuid.UUID(int=0)),
            "filename": "legacy.txt",
        }
    )

    assert document.active_generation is None
    assert document.index_state == "idle"
    assert document.embedding_dimension is None
