from __future__ import annotations

import asyncio
import uuid

import pytest

from app.storage.models.kb import EMBED_DIM, KbChunk
from app.storage.repositories.kb_lance import (
    FTS_INDEX_NAME,
    LANCE_TABLE_NAME,
    KbLanceStore,
    reset_lance_store,
)

_DEFAULT_VECTOR = object()


@pytest.fixture
def lance_store(tmp_path):
    reset_lance_store()
    store = KbLanceStore(tmp_path / "kb")
    yield store
    reset_lance_store()


def _chunk(
    *,
    content: str,
    retrieval_text: str | None = None,
    document_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None,
    generation: str = "gen-1",
    vector=_DEFAULT_VECTOR,
) -> KbChunk:
    return KbChunk(
        document_id=document_id or uuid.uuid4(),
        collection_id=collection_id or uuid.uuid4(),
        org_id=uuid.uuid4(),
        chunk_index=0,
        content=content,
        retrieval_text=retrieval_text if retrieval_text is not None else content,
        generation=generation,
        embedding=[0.0] * EMBED_DIM if vector is _DEFAULT_VECTOR else vector,
    )


@pytest.mark.asyncio
async def test_ensure_ready_is_idempotent_and_persists_icu_fts(lance_store, monkeypatch):
    from lancedb.table import LanceTable

    create_index = LanceTable.create_index
    create_calls = []

    def count_index_creation(table, *args, **kwargs):
        create_calls.append((args, kwargs))
        return create_index(table, *args, **kwargs)

    monkeypatch.setattr(LanceTable, "create_index", count_index_creation)
    await asyncio.gather(lance_store.ensure_ready(), lance_store.ensure_ready())
    reset_lance_store()
    reopened_store = KbLanceStore(lance_store.kb_root)
    await reopened_store.ensure_ready()

    indexes = list(reopened_store._table().list_indices())
    assert len(create_calls) == 1
    assert create_calls[0][1]["config"].base_tokenizer == "icu"
    assert len(indexes) == 1
    assert indexes[0].name == FTS_INDEX_NAME
    assert indexes[0].columns == ["retrieval_text"]
    assert LANCE_TABLE_NAME == "chunks_v2"


@pytest.mark.asyncio
async def test_fts_searches_chinese_mixed_language_and_identifiers(lance_store):
    collection_id = uuid.uuid4()
    chunks = [
        _chunk(content="Agent 检索架构", retrieval_text="人工智能代理 的 检索 架构", collection_id=collection_id),
        _chunk(content="MCP 工具发现", retrieval_text="MCP 工具 discovery", collection_id=collection_id),
        _chunk(content="FTS 配置", retrieval_text="create_fts_index 参数", collection_id=collection_id),
    ]
    await lance_store.write_generation(chunks, active=True)

    for query, expected in (
        ("代理", chunks[0]),
        ("MCP discovery", chunks[1]),
        ("create_fts_index", chunks[2]),
    ):
        hits = await lance_store.fts_search(query, [collection_id], limit=5)
        assert [hit.chunk_id for hit in hits] == [expected.id]
        assert hits[0].content == expected.content


@pytest.mark.asyncio
async def test_new_generation_is_searchable_without_replacing_fts_index(lance_store):
    collection_id = uuid.uuid4()
    document_id = uuid.uuid4()
    await lance_store.ensure_ready()
    before = list(lance_store._table().list_indices())
    first = _chunk(content="first passage", document_id=document_id, collection_id=collection_id)
    second = _chunk(
        content="second passage",
        document_id=document_id,
        collection_id=collection_id,
        generation="gen-2",
    )

    await lance_store.write_generation([first], active=True)
    await lance_store.write_generation([second], active=True)
    after = list(lance_store._table().list_indices())

    assert len(after) == len(before) == 1
    hits = await lance_store.fts_search("second passage", [collection_id], limit=5)
    assert second.id in [hit.chunk_id for hit in hits]


@pytest.mark.asyncio
async def test_search_excludes_inactive_and_other_collections(lance_store):
    collection_id = uuid.uuid4()
    other_collection_id = uuid.uuid4()
    visible = _chunk(
        content="shared searchable phrase",
        collection_id=collection_id,
        vector=[1.0] + [0.0] * (EMBED_DIM - 1),
    )
    inactive = _chunk(
        content="shared searchable phrase",
        collection_id=collection_id,
        generation="building",
        vector=[1.0] + [0.0] * (EMBED_DIM - 1),
    )
    other_collection = _chunk(
        content="shared searchable phrase",
        collection_id=other_collection_id,
        vector=[1.0] + [0.0] * (EMBED_DIM - 1),
    )
    await lance_store.write_generation([visible], active=True)
    await lance_store.write_generation([inactive], active=False)
    await lance_store.write_generation([other_collection], active=True)

    hits = await lance_store.fts_search("shared searchable phrase", [collection_id], limit=10)
    assert [hit.chunk_id for hit in hits] == [visible.id]
    vector_hits = await lance_store.vector_search([1.0] + [0.0] * (EMBED_DIM - 1), [collection_id], limit=10)
    assert [hit.chunk_id for hit in vector_hits] == [visible.id]


@pytest.mark.asyncio
async def test_vector_search_returns_cosine_neighbors(lance_store):
    collection_id = uuid.uuid4()
    query = [0.0] * EMBED_DIM
    query[0] = 1.0
    near = [0.0] * EMBED_DIM
    near[0] = 0.99
    near[1] = 0.01
    far = [0.0] * EMBED_DIM
    far[1] = 1.0
    chunks = [
        _chunk(content="far vector", collection_id=collection_id, vector=far),
        _chunk(content="near vector", collection_id=collection_id, vector=near),
    ]
    await lance_store.write_generation(chunks, active=True)

    hits = await lance_store.vector_search(query, [collection_id], limit=2)
    assert [hit.chunk_id for hit in hits] == [chunks[1].id, chunks[0].id]


@pytest.mark.asyncio
async def test_generation_validation_reports_count_dimension_and_empty_text(lance_store):
    document_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    chunks = [
        _chunk(
            content="visible content",
            retrieval_text=" ",
            document_id=document_id,
            collection_id=collection_id,
            vector=[1.0] * EMBED_DIM,
        ),
        _chunk(
            content="valid content",
            document_id=document_id,
            collection_id=collection_id,
            vector=[0.0] * EMBED_DIM,
        ),
    ]
    await lance_store.write_generation(chunks)

    validation = await lance_store.validate_generation(document_id, "gen-1", expected_count=3)

    assert validation.row_count == 2
    assert not validation.row_count_matches
    assert validation.unique_chunk_count == 2
    assert validation.vector_dimensions_valid
    assert validation.empty_text_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("vector", [None, [0.0] * (EMBED_DIM - 1)])
async def test_write_generation_rejects_missing_or_wrong_dimension_vectors(lance_store, vector):
    with pytest.raises(ValueError, match="embedding"):
        await lance_store.write_generation([_chunk(content="invalid vector", vector=vector)])

    assert lance_store._table().count_rows() == 0


@pytest.mark.asyncio
async def test_delete_generation_preserves_other_generation(lance_store):
    document_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    old = _chunk(content="old generation", document_id=document_id, collection_id=collection_id)
    new = _chunk(
        content="new generation",
        document_id=document_id,
        collection_id=collection_id,
        generation="gen-2",
    )
    await lance_store.write_generation([old], active=True)
    await lance_store.write_generation([new], active=True)

    await lance_store.delete_generation(document_id, "gen-1")

    validation = await lance_store.validate_generation(document_id, "gen-1", expected_count=0)
    assert validation.row_count == 0
    assert validation.unique_chunk_count == 0
    remaining = await lance_store.fts_search("new generation", [collection_id], limit=5)
    assert [hit.chunk_id for hit in remaining] == [new.id]
