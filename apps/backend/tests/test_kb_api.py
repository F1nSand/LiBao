"""T6 KB 集合/文档 + 索引流水线测试（DB-backed，FakeEmbedder 注入 pipeline）。

覆盖：集合 CRUD/重名 40905/40407；上传 txt → uploaded → pipeline → indexed(chunk_count)；
空文本 failed；reindex 幂等；处理中 reindex/archive → 40901；删除级联硬删 chunks；跨 org 404。
"""
from __future__ import annotations

import uuid

import pytest

from app.api.routers.kb import _decode_text
from app.core.errors import AppError
from app.services.kb import KbService
from app.services.kb_pipeline import process_document
from app.services.serializers import kb_document_progress
from app.storage.file.store import get_store
from app.storage.models import User
from app.storage.repositories.kb import KbRepository


class FakeEmbedder:
    """确定性 embedding（维度 1024），带调用计数。"""

    def __init__(self) -> None:
        self.calls = 0

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[0.1 * i] * 1024 for i in range(len(texts))]


@pytest.fixture
async def kb_fixture(monkeypatch):
    store = get_store()
    store.bm25 = __import__("app.storage.repositories.bm25", fromlist=["BM25Index"]).BM25Index()
    # 禁自动后台链（测试手动调 process_document 控制状态机）
    monkeypatch.setattr("app.services.kb._spawn_pipeline", lambda doc_id: None)
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"kb_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        user2 = User(username=f"kb2_{uid}", password_hash="hashed", name="T2", role="admin", org_id=uuid.UUID(int=0))
        session.add(user2)
        await session.commit()
    yield user, user2


async def _upload_doc(user, svc, name, content, collection_id=None):
    """经服务层上传（模拟 multipart 后的 content 提取），返回 (doc_id, collection_id)。"""
    if collection_id is None:
        async with get_store().session() as session:
            coll = await svc.create_collection(session, user, name=f"coll-{uuid.uuid4().hex[:6]}")
            collection_id = coll.id
    async with get_store().session() as session:
        doc = await svc.upload_document(
            session, user, collection_id, filename=name, content=content, content_type="text/plain"
        )
        return doc.id, collection_id


async def test_collection_crud_and_conflicts(kb_fixture):
    user, user2 = kb_fixture
    svc = KbService()
    async with get_store().session() as session:
        coll = await svc.create_collection(session, user, name="产品手册", chunk_size=512, overlap=64)
        assert coll.name == "产品手册"
        with pytest.raises(AppError) as exc:
            await svc.create_collection(session, user, name="产品手册")  # 重名
        assert exc.value.code == 40905
        got = await svc.get_collection(session, user, coll.id)
        assert got.id == coll.id
        got2 = await svc.get_collection(session, user2, coll.id)  # org 折叠：无跨 org 隔离
        assert got2.id == coll.id


async def test_upload_and_pipeline_to_indexed(kb_fixture):
    user, user2 = kb_fixture
    svc = KbService()
    embedder = FakeEmbedder()
    doc_id, coll_id = await _upload_doc(user, svc, "guide.md", "内容内容" * 300)  # ~900 字 → 2 块
    async with get_store().session() as session:
        doc = await svc.get_document(session, user, doc_id)
        assert doc.status == "uploaded"
    await process_document(doc_id, embedder=embedder)
    async with get_store().session() as session:
        doc = await svc.get_document(session, user, doc_id)
        assert doc.status == "indexed"
        assert doc.chunk_count >= 2  # 512/64 滑窗
        chunks = await KbRepository(session).list_chunks(doc_id)
        assert len(chunks) == doc.chunk_count
        assert embedder.calls >= 1


async def test_empty_text_fails(kb_fixture):
    user, user2 = kb_fixture
    svc = KbService()
    doc_id, _ = await _upload_doc(user, svc, "empty.txt", "   \n  ")
    await process_document(doc_id, embedder=FakeEmbedder())
    async with get_store().session() as session:
        doc = await svc.get_document(session, user, doc_id)
        assert doc.status == "failed"
        assert doc.error


async def test_reindex_idempotent(kb_fixture):
    user, user2 = kb_fixture
    svc = KbService()
    doc_id, _ = await _upload_doc(user, svc, "doc.txt", "abcdef" * 200)
    await process_document(doc_id, embedder=FakeEmbedder())
    async with get_store().session() as session:
        before = await svc.get_document(session, user, doc_id)
        assert before.status == "indexed"
    async with get_store().session() as session:
        await svc.reindex_document(session, user, doc_id)
    await process_document(doc_id, embedder=FakeEmbedder())
    async with get_store().session() as session:
        after = await svc.get_document(session, user, doc_id)
        assert after.status == "indexed"
        assert after.chunk_count == before.chunk_count  # 幂等，不翻倍
        chunks = await KbRepository(session).list_chunks(doc_id)
        assert len(chunks) == before.chunk_count


async def test_processing_conflict_40901(kb_fixture):
    user, user2 = kb_fixture
    svc = KbService()
    doc_id, _ = await _upload_doc(user, svc, "doc.txt", "x" * 100)
    async with get_store().session() as session:
        doc = await svc.get_document(session, user, doc_id)
        doc.status = "indexing"  # 模拟处理中（index.json 落盘）
        await KbRepository().persist_document(doc)
        with pytest.raises(AppError) as exc:
            await svc.reindex_document(session, user, doc_id)
        assert exc.value.code == 40901
        with pytest.raises(AppError) as exc:
            await svc.archive_document(session, user, doc_id, "archived")
        assert exc.value.code == 40901


async def test_archive_and_delete_cascade(kb_fixture):
    user, user2 = kb_fixture
    svc = KbService()
    doc_id, _ = await _upload_doc(user, svc, "doc.txt", "abc" * 200)
    await process_document(doc_id, embedder=FakeEmbedder())
    async with get_store().session() as session:
        await svc.archive_document(session, user, doc_id, "archived")
        doc = await svc.get_document(session, user, doc_id)
        assert doc.status == "archived"
    # 删除级联硬删 chunks
    async with get_store().session() as session:
        await svc.delete_document(session, user, doc_id)
        with pytest.raises(AppError):
            await svc.get_document(session, user, doc_id)
        assert await KbRepository().list_chunks(doc_id) == []  # chunks 硬删


async def test_delete_collection_cascades(kb_fixture):
    user, user2 = kb_fixture
    svc = KbService()
    doc_id, coll_id = await _upload_doc(user, svc, "doc.txt", "abc" * 100)
    await process_document(doc_id, embedder=FakeEmbedder())
    async with get_store().session() as session:
        await svc.delete_collection(session, user, coll_id)
        with pytest.raises(AppError) as exc:
            await svc.get_collection(session, user, coll_id)
        assert exc.value.code == 40407
        # chunks 硬删（文件化：index.json chunks 清空 + BM25 语料无该集合）
        index = await KbRepository()._load_index(coll_id)  # noqa: SLF001
        assert index["chunks"] == {}
        assert get_store().bm25.search("abc", collection_ids=[str(coll_id)]) == []


async def test_progress_is_number_for_all_statuses():
    """S2：KB 文档 progress 恒为 number（前端 KbDocument.progress?: number，ChunkStatus 以 >=100 判成功）。"""
    for status, expected in [
        ("uploaded", 0),
        ("chunking", 30),
        ("indexing", 70),
        ("indexed", 100),
        ("failed", 100),
        ("archived", 100),
    ]:
        assert kb_document_progress(status) == expected
        assert isinstance(kb_document_progress(status), int)


async def test_pipeline_insert_failure_marks_failed(kb_fixture, monkeypatch):
    """C1：插库段异常 → 文档置 failed（不再永久卡 indexing）。"""
    user, user2 = kb_fixture
    svc = KbService()
    embedder = FakeEmbedder()

    async def boom(*a, **k):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(KbRepository, "insert_chunks", boom)
    doc_id, _ = await _upload_doc(user, svc, "doc.txt", "abc" * 200)
    await process_document(doc_id, embedder=embedder)
    async with get_store().session() as session:
        doc = await svc.get_document(session, user, doc_id)
        assert doc.status == "failed"
        assert "索引落库失败" in (doc.error or "")


async def test_document_counts(kb_fixture):
    """S11：document_counts 统计非软删文档数（单条 GROUP BY）。"""
    user, user2 = kb_fixture
    svc = KbService()
    async with get_store().session() as session:
        coll = await svc.create_collection(session, user, name="count-coll")
    for name, content in [("a.txt", "aaa"), ("b.txt", "bbb")]:
        await _upload_doc(user, svc, name, content, collection_id=coll.id)
    async with get_store().session() as session:
        counts = await svc.document_counts(session, user, [coll.id])
        assert counts[coll.id] == 2


async def test_empty_content_40001(kb_fixture):
    """S8：空内容 → 40001（参数缺失，非 40014 超长）。"""
    user, user2 = kb_fixture
    svc = KbService()
    async with get_store().session() as session:
        coll = await svc.create_collection(session, user, name="empty-coll")
        with pytest.raises(AppError) as exc:
            await svc.upload_document(session, user, coll.id, filename="e.txt", content="", content_type="text/plain")
        assert exc.value.code == 40001


async def test_decode_text_invalid_utf8_40012():
    """S3：KB 上传非法 UTF-8 → 40012（纯单元；原 ValueError → 50001）。"""
    with pytest.raises(AppError) as exc:
        _decode_text(b"\xff\xfe\x00")
    assert exc.value.code == 40012
    assert _decode_text("你好".encode()) == "你好"


async def test_any_user_can_access_after_org_fold(kb_fixture):
    """org 折叠：他人 org 的用户（固定 admin 恒同 org）可正常访问文档。"""
    user, user2 = kb_fixture
    svc = KbService()
    doc_id, _ = await _upload_doc(user, svc, "doc.txt", "abc")
    async with get_store().session() as session:
        doc = await svc.get_document(session, user2, doc_id)  # 折叠后无跨 org 隔离
        assert doc is not None
        assert doc.id == doc_id
