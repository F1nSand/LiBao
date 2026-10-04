from __future__ import annotations

import uuid

import pytest

from app.core import bootstrap
from app.storage.models.kb import EMBED_DIM, KbChunk
from app.storage.repositories.bm25 import BM25Index
from app.storage.repositories.kb import KbRepository


async def _seed_legacy_document():
    repo = KbRepository()
    repo.store.bm25 = BM25Index()
    collection = await repo.create_collection(uuid.UUID(int=0), f"bootstrap-{uuid.uuid4().hex[:8]}", 512, 64)
    document = await repo.create_document(
        collection_id=collection.id,
        org_id=uuid.UUID(int=0),
        filename="legacy.txt",
        content_type="text/plain",
        size_bytes=24,
        content="bootstrap legacy passage",
    )
    document.status = "indexed"
    vector = [0.25] * EMBED_DIM
    await repo.insert_chunks(
        [
            KbChunk(
                document_id=document.id,
                collection_id=collection.id,
                org_id=document.org_id,
                chunk_index=0,
                content=document.content,
                embedding=vector,
            )
        ]
    )
    await repo.persist_document(document)
    manifest = await repo.manifests.load(collection.id)
    await repo.manifests.save(
        collection.id,
        {
            "version": 1,
            "documents": {str(document.id): manifest["documents"][str(document.id)]},
            "chunks": {
                str(document.id): [
                    {
                        "chunk_id": manifest["chunks"][str(document.id)]["legacy-v1"][0]["chunk_id"],
                        "chunk_index": 0,
                        "content": document.content,
                    }
                ]
            },
        },
        version=1,
    )
    return repo


class Bm25Spy:
    instances: list[Bm25Spy] = []

    def __init__(self):
        self.rebuild_calls = 0
        self.chunks = []
        self.index = BM25Index()
        type(self).instances.append(self)

    def rebuild(self, chunks):
        self.rebuild_calls += 1
        self.chunks = chunks
        self.index.rebuild(chunks)

    def search(self, query, collection_ids=None, limit=50):
        return self.index.search(query, collection_ids=collection_ids, limit=limit)


@pytest.mark.asyncio
async def test_completed_migration_skips_bm25_rebuild_and_future_migration_writes(monkeypatch):
    repo = await _seed_legacy_document()
    Bm25Spy.instances.clear()
    monkeypatch.setattr("app.storage.repositories.bm25.BM25Index", Bm25Spy)

    mode, report = await bootstrap.initialize_kb_indexing(repo.store)
    assert mode == "v2"
    assert report.complete
    assert Bm25Spy.instances[-1].rebuild_calls == 0

    writes = 0
    original_write = repo.lance.write_generation

    async def count_writes(chunks, *, active=False):
        nonlocal writes
        writes += 1
        await original_write(chunks, active=active)

    monkeypatch.setattr(repo.lance, "write_generation", count_writes)
    mode, report = await bootstrap.initialize_kb_indexing(repo.store)

    assert mode == "v2"
    assert report.complete
    assert writes == 0
    assert Bm25Spy.instances[-1].rebuild_calls == 0


@pytest.mark.asyncio
async def test_migration_failure_uses_bm25_degraded_mode_then_retries(monkeypatch):
    repo = await _seed_legacy_document()
    Bm25Spy.instances.clear()
    monkeypatch.setattr("app.storage.repositories.bm25.BM25Index", Bm25Spy)

    async def fail_migration(_self):
        raise RuntimeError("simulated migration failure")

    from app.services.kb_migration import KbV2Migrator

    original_migrate_all = KbV2Migrator.migrate_all
    monkeypatch.setattr(KbV2Migrator, "migrate_all", fail_migration)
    mode, failed_report = await bootstrap.initialize_kb_indexing(repo.store)

    assert mode == "legacy_degraded"
    assert not failed_report.complete
    assert Bm25Spy.instances[-1].rebuild_calls == 1
    assert Bm25Spy.instances[-1].chunks[0][1] == "bootstrap legacy passage"

    original_fts_search = repo.lance.fts_search
    original_vector_search = repo.lance.vector_search

    async def fail_v2_query(*args, **kwargs):
        raise RuntimeError("simulated v2 outage")

    monkeypatch.setattr(repo.lance, "fts_search", fail_v2_query)
    monkeypatch.setattr(repo.lance, "vector_search", fail_v2_query)
    lexical = await repo.bm25_search(uuid.UUID(int=0), [], "bootstrap legacy passage")
    semantic = await repo.semantic_search(uuid.UUID(int=0), [], [0.25] * EMBED_DIM)
    assert lexical and lexical[0][1] == "bootstrap legacy passage"
    assert semantic and semantic[0][1] == "bootstrap legacy passage"

    monkeypatch.setattr(KbV2Migrator, "migrate_all", original_migrate_all)
    monkeypatch.setattr(repo.lance, "fts_search", original_fts_search)
    monkeypatch.setattr(repo.lance, "vector_search", original_vector_search)
    mode, recovered_report = await bootstrap.initialize_kb_indexing(repo.store)

    assert mode == "v2"
    assert recovered_report.complete
    assert Bm25Spy.instances[-1].rebuild_calls == 0


@pytest.mark.asyncio
async def test_force_legacy_mode_skips_migration_for_operator_rollback(monkeypatch):
    repo = await _seed_legacy_document()
    Bm25Spy.instances.clear()
    monkeypatch.setattr("app.storage.repositories.bm25.BM25Index", Bm25Spy)

    migrated_mode, migrated_report = await bootstrap.initialize_kb_indexing(repo.store)
    assert migrated_mode == "v2"
    assert migrated_report.complete

    from app.services.kb_migration import KbV2Migrator

    async def fail_if_called(_self):
        raise AssertionError("forced legacy mode must not run migration")

    monkeypatch.setattr(KbV2Migrator, "migrate_all", fail_if_called)
    mode, report = await bootstrap.initialize_kb_indexing(repo.store, force_legacy=True)

    assert mode == "legacy_degraded"
    assert not report.complete
    assert repo.store.kb_force_legacy_mode
    assert Bm25Spy.instances[-1].rebuild_calls == 1

    async def fail_v2_query(*args, **kwargs):
        raise AssertionError("forced legacy mode must not query the v2 index")

    monkeypatch.setattr(repo.lance, "fts_search", fail_v2_query)
    monkeypatch.setattr(repo.lance, "vector_search", fail_v2_query)
    lexical = await repo.bm25_search(uuid.UUID(int=0), [], "bootstrap legacy passage")
    semantic = await repo.semantic_search(uuid.UUID(int=0), [], [0.25] * EMBED_DIM)
    assert lexical and lexical[0][1] == "bootstrap legacy passage"
    assert semantic and semantic[0][1] == "bootstrap legacy passage"
