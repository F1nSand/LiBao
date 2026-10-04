from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.services.kb_generation import KbGenerationService
from app.services.kb_migration import KbV2Migrator
from app.storage.kb.manifest import LEGACY_GENERATION
from app.storage.models.kb import EMBED_DIM, KbChunk
from app.storage.repositories.bm25 import BM25Index
from app.storage.repositories.kb import KbRepository


@pytest.mark.asyncio
async def test_new_collections_and_documents_are_written_as_v2():
    repo = KbRepository()
    collection = await repo.create_collection(uuid.UUID(int=0), "new-v2", 512, 64)
    document = await repo.create_document(
        collection_id=collection.id,
        org_id=uuid.UUID(int=0),
        filename="new.md",
        content_type="text/markdown",
        size_bytes=4,
        content="new!",
    )

    manifest_path = repo.manifests.path_for(collection.id)
    manifest = await repo.manifests.load(collection.id)
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["version"] == 2
    assert manifest["version"] == 2
    assert manifest["documents"][str(document.id)]["active_generation"] is None


@pytest.mark.asyncio
async def test_legacy_vector_reader_returns_all_document_rows():
    repo = KbRepository()
    repo.store.bm25 = BM25Index()
    collection = await repo.create_collection(uuid.UUID(int=0), f"migration-many-{uuid.uuid4().hex[:8]}", 512, 64)
    document = await repo.create_document(
        collection_id=collection.id,
        org_id=uuid.UUID(int=0),
        filename="many.md",
        content_type="text/markdown",
        size_bytes=100,
        content="many legacy chunks",
    )
    document.status = "indexed"
    await repo.persist_document(document)
    chunks = [
        KbChunk(
            document_id=document.id,
            collection_id=collection.id,
            org_id=document.org_id,
            chunk_index=index,
            content=f"legacy chunk {index}",
            embedding=[float(index + 1) / EMBED_DIM] * EMBED_DIM,
        )
        for index in range(17)
    ]
    await repo.insert_chunks(chunks)

    rows = await repo.legacy_vector_rows(document.id)

    assert len(rows) == 17
    assert {row["chunk_id"] for row in rows} == {str(chunk.id) for chunk in chunks}


async def _legacy_document(content: str = "legacy MCP retrieval passage"):
    repo = KbRepository()
    repo.store.bm25 = BM25Index()
    collection = await repo.create_collection(uuid.UUID(int=0), f"migration-{uuid.uuid4().hex[:8]}", 512, 64)
    document = await repo.create_document(
        collection_id=collection.id,
        org_id=uuid.UUID(int=0),
        filename="legacy.md",
        content_type="text/markdown",
        size_bytes=len(content.encode()),
        content=content,
    )
    document.status = "indexed"
    document.chunk_count = 1
    vector = [float(index + 1) / EMBED_DIM for index in range(EMBED_DIM)]
    chunk = KbChunk(
        document_id=document.id,
        collection_id=collection.id,
        org_id=document.org_id,
        chunk_index=0,
        content=content,
        embedding=vector,
    )
    await repo.insert_chunks([chunk])
    await repo.persist_document(document)
    await repo.manifests.save(
        collection.id,
        {
            "version": 1,
            "documents": {str(document.id): document.to_dict()},
            "chunks": {
                str(document.id): [
                    {"chunk_id": str(chunk.id), "chunk_index": 0, "content": content}
                ]
            },
        },
        version=1,
    )
    return repo, collection, document, chunk, vector


@pytest.mark.asyncio
async def test_migrates_v1_text_and_existing_vector_without_reembedding():
    repo, collection, document, chunk, vector = await _legacy_document()

    result = await KbV2Migrator(repo=repo).migrate_document(collection.id, document.id)

    assert result.status == "migrated"
    assert result.chunk_count == 1
    manifest = await repo.manifests.load(collection.id)
    doc_state = manifest["documents"][str(document.id)]
    assert manifest["version"] == 2
    assert doc_state["active_generation"] == f"migrated-v1-{document.id}"
    assert manifest["chunks"][str(document.id)][LEGACY_GENERATION][0]["chunk_id"] == str(chunk.id)
    assert manifest["chunks"][str(document.id)][doc_state["active_generation"]][0]["retrieval_text"]

    migrated = await repo.lance.validate_generation(document.id, doc_state["active_generation"], 1)
    assert migrated.row_count_matches and migrated.vector_dimensions_valid
    assert (await repo.legacy_vector_rows(document.id))[0]["vector"] == vector
    assert (await repo.lance.fts_search("MCP retrieval", [collection.id], 10))[0].chunk_id == chunk.id

    repo.store.kb_index_mode = "v2"
    semantic_hits = await repo.semantic_search(uuid.UUID(int=0), [collection.id], vector)
    lexical_hits = await repo.hybrid_search(
        uuid.UUID(int=0), [collection.id], "MCP retrieval", hybrid={"semantic": 0, "bm25": 1}
    )
    assert semantic_hits[0][0] == chunk.id
    assert lexical_hits[0]["chunk_id"] == str(chunk.id)


@pytest.mark.asyncio
async def test_migrating_an_already_active_document_is_idempotent():
    repo, collection, document, _chunk, _vector = await _legacy_document()
    migrator = KbV2Migrator(repo=repo)
    first = await migrator.migrate_document(collection.id, document.id)
    second = await migrator.migrate_document(collection.id, document.id)

    assert first.status == "migrated"
    assert second.status == "skipped"
    manifest = await repo.manifests.load(collection.id)
    active_generation = manifest["documents"][str(document.id)]["active_generation"]
    validation = await repo.lance.validate_generation(document.id, active_generation, 1)
    assert validation.row_count == 1


@pytest.mark.asyncio
async def test_missing_legacy_vector_marks_document_for_reindex_without_touching_v1(monkeypatch):
    repo, collection, document, chunk, _vector = await _legacy_document()
    path = repo.manifests.path_for(collection.id)
    original_manifest = path.read_bytes()
    original_vectors = await repo.legacy_vector_rows(document.id)

    async def missing_vectors(_document_id):
        return []

    monkeypatch.setattr(repo, "legacy_vector_rows", missing_vectors)
    result = await KbV2Migrator(repo=repo).migrate_document(collection.id, document.id)

    assert result.status == "reindex_required"
    assert path.read_bytes() == original_manifest
    assert (await repo.legacy_vector_rows(document.id)) == []
    assert original_vectors[0]["chunk_id"] == str(chunk.id)
    assert (await repo.lance.validate_generation(document.id, f"migrated-v1-{document.id}", 0)).row_count == 0


@pytest.mark.asyncio
async def test_reindex_required_is_recorded_and_retried_by_the_migration_ledger(monkeypatch):
    repo, _collection, document, _chunk, _vector = await _legacy_document()
    original_read = repo.legacy_vector_rows

    async def missing_vectors(_document_id):
        return []

    monkeypatch.setattr(repo, "legacy_vector_rows", missing_vectors)
    migrator = KbV2Migrator(repo=repo)
    pending = await migrator.migrate_all()
    ledger_path = repo.store.kb_root / "migration-v2.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))

    assert pending.total == 1
    assert pending.reindex_required == 1
    assert not pending.complete
    assert ledger["started_at"]
    assert ledger["legacy_fallback_required"] is True
    assert ledger["completed_at"] is None
    assert ledger["documents"][str(document.id)]["status"] == "reindex_required"

    monkeypatch.setattr(repo, "legacy_vector_rows", original_read)
    completed = await KbV2Migrator(repo=repo).migrate_all()
    assert completed.complete
    assert completed.migrated == 1
    assert completed.reindex_required == 0


@pytest.mark.asyncio
async def test_incompatible_legacy_vector_dimension_marks_document_for_reindex(monkeypatch):
    repo, collection, document, chunk, _vector = await _legacy_document()
    path = repo.manifests.path_for(collection.id)
    original_manifest = path.read_bytes()

    async def short_vector(_document_id):
        return [{"chunk_id": str(chunk.id), "vector": [0.5, 0.75]}]

    monkeypatch.setattr(repo, "legacy_vector_rows", short_vector)
    result = await KbV2Migrator(repo=repo).migrate_document(collection.id, document.id)

    assert result.status == "reindex_required"
    assert "dimension" in result.reason
    assert path.read_bytes() == original_manifest
    assert (await repo.lance.validate_generation(document.id, f"migrated-v1-{document.id}", 0)).row_count == 0


@pytest.mark.asyncio
async def test_failed_cutover_rolls_back_new_rows_and_leaves_v1_untouched(monkeypatch):
    repo, collection, document, chunk, vector = await _legacy_document()
    path = repo.manifests.path_for(collection.id)
    original_manifest = path.read_bytes()
    original_vectors = await repo.legacy_vector_rows(document.id)
    original_validate = repo.lance.validate_generation

    async def fail_validation(_document_id, _generation, _expected_count):
        raise RuntimeError("simulated validation outage")

    monkeypatch.setattr(repo.lance, "validate_generation", fail_validation)
    result = await KbV2Migrator(repo=repo).migrate_document(collection.id, document.id)

    assert result.status == "failed"
    assert path.read_bytes() == original_manifest
    assert (await repo.legacy_vector_rows(document.id))[0]["vector"] == vector
    assert original_vectors[0]["chunk_id"] == str(chunk.id)
    monkeypatch.setattr(repo.lance, "validate_generation", original_validate)
    assert (await original_validate(document.id, f"migrated-v1-{document.id}", 0)).row_count == 0


@pytest.mark.asyncio
async def test_cancellation_after_manifest_activation_keeps_referenced_generation(monkeypatch):
    repo, collection, document, _chunk, _vector = await _legacy_document()
    original_activate = KbGenerationService.activate

    async def activate_then_cancel(service, migrated_document, generation, chunks):
        await original_activate(service, migrated_document, generation, chunks)
        raise asyncio.CancelledError

    monkeypatch.setattr(KbGenerationService, "activate", activate_then_cancel)

    with pytest.raises(asyncio.CancelledError):
        await KbV2Migrator(repo=repo).migrate_document(collection.id, document.id)

    manifest = await repo.manifests.load(collection.id)
    generation = f"migrated-v1-{document.id}"
    assert manifest["documents"][str(document.id)]["active_generation"] == generation
    validation = await repo.lance.validate_generation(document.id, generation, 1)
    assert validation.row_count_matches
    assert validation.unique_chunk_count == 1


@pytest.mark.asyncio
async def test_partial_lance_write_failure_removes_the_unactivated_generation(monkeypatch):
    repo, collection, document, _chunk, _vector = await _legacy_document()
    path = repo.manifests.path_for(collection.id)
    original_manifest = path.read_bytes()
    original_write = repo.lance.write_generation

    async def write_then_fail(chunks, *, active=False):
        await original_write(chunks, active=active)
        raise RuntimeError("simulated partial write failure")

    monkeypatch.setattr(repo.lance, "write_generation", write_then_fail)
    result = await KbV2Migrator(repo=repo).migrate_document(collection.id, document.id)

    assert result.status == "failed"
    assert path.read_bytes() == original_manifest
    monkeypatch.setattr(repo.lance, "write_generation", original_write)
    validation = await repo.lance.validate_generation(document.id, f"migrated-v1-{document.id}", 0)
    assert validation.row_count == 0


@pytest.mark.asyncio
async def test_migrate_all_resumes_after_interruption_between_documents(monkeypatch):
    repo, collection_one, document_one, _chunk_one, _vector_one = await _legacy_document("first legacy passage")
    _, collection_two, document_two, _chunk_two, _vector_two = await _legacy_document("second legacy passage")
    migrator = KbV2Migrator(repo=repo)
    original_write = repo.lance.write_generation
    writes = 0

    async def interrupt_before_second_write(chunks, *, active=False):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise asyncio.CancelledError
        await original_write(chunks, active=active)

    monkeypatch.setattr(repo.lance, "write_generation", interrupt_before_second_write)
    with pytest.raises(asyncio.CancelledError):
        await migrator.migrate_all()

    ledger_path = repo.store.kb_root / "migration-v2.json"
    interrupted_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert set(interrupted_ledger) == {
        "version",
        "started_at",
        "completed_at",
        "documents",
        "last_error",
        "legacy_fallback_required",
    }
    assert sum(item["status"] == "migrated" for item in interrupted_ledger["documents"].values()) == 1

    monkeypatch.setattr(repo.lance, "write_generation", original_write)
    report = await KbV2Migrator(repo=repo).migrate_all()

    assert report.total == 2
    assert report.migrated == 2
    assert report.complete
    assert not list(repo.store.kb_root.glob("*.tmp"))
    assert (await repo.legacy_vector_rows(document_one.id))
    assert (await repo.legacy_vector_rows(document_two.id))
    assert (await repo.manifests.load(collection_one.id))["documents"][str(document_one.id)]["active_generation"]
    assert (await repo.manifests.load(collection_two.id))["documents"][str(document_two.id)]["active_generation"]
