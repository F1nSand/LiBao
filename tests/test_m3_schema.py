"""T1 M3 数据层测试（DB-backed）：迁移 0004 表、pgvector 列、GENERATED tsvector、
UNIQUE 约束、软删语义、HNSW/GIN 索引。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, select, text

from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import (
    KbChunk,
    KbCollection,
    KbDocument,
    LongTermMemory,
    LongTermMemoryVersion,
    Org,
    User,
)
from tests.conftest import requires_db

pytestmark = requires_db

TABLES = [
    "longterm_memory",
    "longterm_memory_version",
    "kb_collections",
    "kb_documents",
    "kb_chunks",
    "attachments",
]


@pytest.fixture
async def m3_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-m3-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"m3_{uid}", password_hash="x", name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.commit()
    yield sessionmaker, user
    await engine.dispose()


async def test_all_seven_tables_exist(m3_fixture):
    sessionmaker, user = m3_fixture
    async with get_store().session(sessionmaker) as session:
        existing = set(await session.run_sync(lambda s: inspect(s.get_bind()).get_table_names()))
        for t in TABLES:
            assert t in existing, f"缺少表 {t}"


async def test_pgvector_extension_enabled(m3_fixture):
    sessionmaker, user = m3_fixture
    async with get_store().session(sessionmaker) as session:
        ext = (await session.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'"))).scalar_one()
        assert ext == "vector"


async def test_vector_column_insert_and_cosine_search(m3_fixture):
    sessionmaker, user = m3_fixture
    async with get_store().session(sessionmaker) as session:
        org = user.org_id
        coll = KbCollection(org_id=org, name=f"vec-{uuid.uuid4().hex[:6]}")
        session.add(coll)
        await session.flush()
        doc = KbDocument(
            collection_id=coll.id, org_id=org, filename="a.txt", content_type="text/plain",
            size_bytes=10, content="x", status="indexed",
        )
        session.add(doc)
        await session.flush()
        c1 = KbChunk(
            document_id=doc.id, collection_id=coll.id, org_id=org, chunk_index=0,
            content="hello", embedding=[1.0] * 1024,
        )
        session.add(
            KbChunk(
                document_id=doc.id, collection_id=coll.id, org_id=org, chunk_index=1,
                content="world", embedding=[0.0] * 1024,
            )
        )
        session.add(c1)
        await session.commit()
        # cosine_distance 排序：query [1.0]*1024 应命中 c1

        qv = [1.0] * 1024
        top = (
            await session.execute(
                select(KbChunk.id)
                .where(KbChunk.collection_id == coll.id)
                .order_by(KbChunk.embedding.cosine_distance(qv))
                .limit(1)
            )
        ).scalar_one()
        assert top == c1.id


async def test_generated_tsv_contains_cjk_unigrams(m3_fixture):
    sessionmaker, user = m3_fixture
    async with get_store().session(sessionmaker) as session:
        org = user.org_id
        coll = KbCollection(org_id=org, name=f"tsv-{uuid.uuid4().hex[:6]}")
        session.add(coll)
        await session.flush()
        doc = KbDocument(
            collection_id=coll.id, org_id=org, filename="a.txt", content_type="text/plain",
            size_bytes=10, content="x", status="indexed",
        )
        session.add(doc)
        await session.flush()
        chunk = KbChunk(
            document_id=doc.id, collection_id=coll.id, org_id=org, chunk_index=0,
            content="今天天气很好", embedding=None,
        )
        session.add(chunk)
        await session.commit()
        # GENERATED 列：中文逐字插空格 → tsvector 含每个汉字 unigram
        tsv = (
            await session.execute(select(KbChunk.content_tsv).where(KbChunk.id == chunk.id))
        ).scalar_one()
        text_repr = str(tsv)
        # tsvector 文本格式为 "'今':1 '天':2,3 ..." —— 每个汉字是独立 token（unigram）
        for ch in "今天天气":
            assert ch in text_repr, f"缺少汉字 token {ch}: {text_repr}"


async def test_memory_version_unique_constraint(m3_fixture):
    sessionmaker, user = m3_fixture
    async with get_store().session(sessionmaker) as session:
        card = LongTermMemory(user_id=user.id, card_type="note", content={"text": "a"}, importance=0.5)
        session.add(card)
        await session.flush()
        v1 = LongTermMemoryVersion(memory_id=card.id, version=1, content={"text": "a"}, importance=0.5)
        session.add(v1)
        await session.commit()
        v1_dup = LongTermMemoryVersion(memory_id=card.id, version=1, content={"text": "b"}, importance=0.6)
        session.add(v1_dup)
        with pytest.raises(Exception) as exc:  # noqa: B017  UNIQUE 违反的具体类型由驱动决定
            await session.commit()
        assert "unique" in str(exc.value).lower() or "duplicate" in str(exc.value).lower()
        await session.rollback()


async def test_kb_chunks_hnsw_and_gin_indexes(m3_fixture):
    sessionmaker, user = m3_fixture
    async with get_store().session(sessionmaker) as session:
        rows = await session.execute(text("SELECT indexname FROM pg_indexes WHERE tablename='kb_chunks'"))
        indexes = rows.scalars().all()
        assert any("hnsw" in i for i in indexes), f"缺少 HNSW 索引: {indexes}"
        assert any("gin" in i for i in indexes), f"缺少 GIN 索引: {indexes}"
        # UNIQUE(document_id, chunk_index)
        assert any("uniq" in i for i in indexes), f"缺少 UNIQUE 约束: {indexes}"


async def test_soft_delete_semantics(m3_fixture):
    sessionmaker, user = m3_fixture
    async with get_store().session(sessionmaker) as session:
        card = LongTermMemory(user_id=user.id, card_type="note", content={"text": "a"}, importance=0.5)
        session.add(card)
        await session.commit()
        card.deleted_at = card.deleted_at  # BaseModel 软删列存在
        from datetime import UTC, datetime

        card.deleted_at = datetime.now(UTC)
        await session.commit()
        remaining = (
            await session.execute(select(LongTermMemory).where(LongTermMemory.id == card.id))
        ).scalar_one()
        assert remaining.deleted_at is not None
