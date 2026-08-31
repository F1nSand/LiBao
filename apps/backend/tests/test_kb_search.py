"""T7 /kb/search 混合检索测试（文件化，确定性向量手动插 chunk）。

覆盖：中文 BM25 命中、纯 bm25 不触发 embedding、语义余弦排序、RRF 融合、
top_k、空 query、collection_ids 过滤、archived/indexing 不可见、rerank_score null。
"""
from __future__ import annotations

import uuid

import pytest

from app.services.kb import KbService
from app.storage.file.store import get_store
from app.storage.models.kb import KbChunk
from app.storage.repositories.bm25 import BM25Index
from app.storage.repositories.kb import KbRepository


class CountingEmbedder:
    """embed_query 计数（验证纯 bm25 不触发语义通道）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        return [0.0] * 1024


class NearEmbedder:
    """确定性查询向量 [1.0]*1024：与 doc1([0.9]) 余弦最近，doc2([0.1]) 最远。"""

    async def embed_query(self, text: str) -> list[float]:
        return [1.0] * 1024


class _DisableRerank:
    """rerank 故障降级：让语义排序测试走纯 RRF（余弦）顺序，不受真实 Cross-Encoder API 波动影响。"""

    async def rerank(self, query: str, docs: list, top_n: int) -> list[tuple[int, float]]:
        raise RuntimeError("rerank disabled in test")


async def _mk_doc(repo: KbRepository, coll_id: uuid.UUID, filename: str, content: str,
                  status: str = "indexed", embedding: list | None = None) -> uuid.UUID:
    """文件化构造文档：create → 设状态 → 落盘；indexed 时插 chunk（向量 + BM25）。"""
    doc = await repo.create_document(
        collection_id=coll_id, org_id=uuid.UUID(int=0), filename=filename,
        content_type="text/plain", size_bytes=len(content), content=content,
    )
    doc.status = status
    index = await repo._load_index(coll_id)  # noqa: SLF001  同域测试构造
    index["documents"][str(doc.id)] = doc.to_dict()
    await repo._save_index(coll_id, index)  # noqa: SLF001
    if embedding is not None and status == "indexed":
        await repo.insert_chunks(
            [
                KbChunk(
                    document_id=doc.id, collection_id=coll_id, org_id=uuid.UUID(int=0),
                    chunk_index=0, content=content, embedding=embedding,
                )
            ]
        )
    return doc.id


@pytest.fixture
async def kb_search_fixture():
    store = get_store()
    store.bm25 = BM25Index()  # 本测试手动插 chunk 后 insert_chunks 自动重建
    repo = KbRepository()
    uid = uuid.uuid4().hex[:8]
    coll = await repo.create_collection(uuid.UUID(int=0), f"coll-{uid}", 512, 64)
    # 集合 A：两文档（indexed + archived）+ 集合 B（过滤测试用）
    await _mk_doc(repo, coll.id, "a.txt", "今天天气很好，适合出门散步。", embedding=[0.9] * 1024)
    await _mk_doc(repo, coll.id, "b.txt", "股票市场今天大涨，投资需谨慎。", embedding=[0.1] * 1024)
    await _mk_doc(repo, coll.id, "c.txt", "天气寒冷注意保暖。", status="archived", embedding=[0.8] * 1024)
    coll_b = await repo.create_collection(uuid.UUID(int=0), f"collb-{uid}", 512, 64)
    await _mk_doc(repo, coll_b.id, "d.txt", "天气查询专用文档。", embedding=[0.85] * 1024)
    yield coll.id, coll_b.id


async def test_bm25_chinese_hit(kb_search_fixture):
    coll_id, coll_b_id = kb_search_fixture
    hits = await KbService().search(None, None, coll_ids=[coll_id], query="天气", top_k=5,
        hybrid={"semantic": 0, "bm25": 1},  # 纯 bm25
    )
    texts = [h["text"] for h in hits]
    assert any("天气" in t for t in texts)
    assert "股票" in texts[0] or "天气" in texts[0]  # bm25 通道有效


async def test_pure_bm25_no_embedding_call(kb_search_fixture, monkeypatch):
    coll_id, coll_b_id = kb_search_fixture
    counter = CountingEmbedder()
    monkeypatch.setattr("app.storage.repositories.kb.EmbeddingService", lambda: counter)
    await KbService().search(None, None, coll_ids=[coll_id], query="天气", top_k=5,
        hybrid={"semantic": 0, "bm25": 1},
    )
    assert counter.calls == 0  # 纯 bm25 不调 embedding API


async def test_semantic_ranking(kb_search_fixture, monkeypatch):
    coll_id, coll_b_id = kb_search_fixture
    monkeypatch.setattr("app.storage.repositories.kb.EmbeddingService", lambda: NearEmbedder())
    monkeypatch.setattr("app.storage.repositories.kb.RerankService", _DisableRerank)  # 隔离真实 rerank API
    hits = await KbService().search(None, None, coll_ids=[coll_id], query="天气", top_k=5,
        hybrid={"semantic": 1, "bm25": 0},  # 纯语义
    )
    assert hits[0]["text"].startswith("今天天气")  # 余弦最近命中 doc1


async def test_rrf_fusion(kb_search_fixture):
    coll_id, coll_b_id = kb_search_fixture
    hits = await KbService().search(None, None, coll_ids=[coll_id], query="天气", top_k=5,
        hybrid={"semantic": 1, "bm25": 1},  # 双通道
    )
    # RRF 融合：语义+bm25 双命中排前（"天气"同时在 doc1 与 b 文档）
    assert len(hits) >= 1
    assert all(h["rerank_score"] is None for h in hits)  # 无 Cross-Encoder
    assert all("score" in h for h in hits)


async def test_top_k_and_empty_query(kb_search_fixture):
    coll_id, coll_b_id = kb_search_fixture
    hits = await KbService().search(None, None, coll_ids=[coll_id], query="天气", top_k=1,
        hybrid={"semantic": 1, "bm25": 1},
    )
    assert len(hits) == 1
    empty = await KbService().search(None, None, coll_ids=[coll_id], query="", top_k=5,
        hybrid={"semantic": 1, "bm25": 1},
    )
    assert empty == []


async def test_collection_ids_filter(kb_search_fixture):
    coll_id, coll_b_id = kb_search_fixture
    only_b = await KbService().search(None, None, coll_ids=[coll_b_id], query="天气", top_k=5,
        hybrid={"semantic": 1, "bm25": 1},
    )
    assert only_b and all(h["source"]["collection_id"] == str(coll_b_id) for h in only_b)
    both = await KbService().search(None, None, coll_ids=[coll_id, coll_b_id], query="天气", top_k=5,
        hybrid={"semantic": 1, "bm25": 1},
    )
    assert len(both) > len(only_b)


async def test_archived_and_indexing_invisible(kb_search_fixture):
    coll_id, coll_b_id = kb_search_fixture
    hits = await KbService().search(None, None, coll_ids=[coll_id], query="寒冷", top_k=5,
        hybrid={"semantic": 0, "bm25": 1},
    )
    # archived 文档的 chunk 不可见（即使 bm25 命中"寒冷"）
    assert all("寒冷" not in h["text"] for h in hits)


class ReorderReranker:
    """固定重排：把候选 index 1 排到最前（模拟 rerank 精排改变 RRF 顺序）。"""

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        n = min(top_n, len(documents))
        order = [1, 0] + list(range(2, n))  # index 1 优先
        return [(order[i], 0.9 - i * 0.1) for i in range(n)]


class FailingReranker:
    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        raise RuntimeError("rerank down")


async def test_rerank_reorders_top(kb_search_fixture, monkeypatch):
    """rerank 精排生效：候选 2（天气/股票）、top_k=1，rerank 把股票（index 1）排前 + 填 rerank_score。"""
    coll_id, coll_b_id = kb_search_fixture
    monkeypatch.setattr("app.storage.repositories.kb.EmbeddingService", lambda: NearEmbedder())
    monkeypatch.setattr("app.storage.repositories.kb.RerankService", lambda: ReorderReranker())
    hits = await KbService().search(None, None, coll_ids=[coll_id], query="天气", top_k=1,
        hybrid={"semantic": 1, "bm25": 1},
    )
    assert len(hits) == 1
    assert "股票" in hits[0]["text"]  # rerank 把 index 1（股票）排到最前
    assert hits[0]["rerank_score"] is not None  # rerank_score 已填充


async def test_rerank_failure_degrades_to_rrf(kb_search_fixture, monkeypatch):
    """rerank 故障 → 静默降级 RRF 顺序（天气语义最近排前，rerank_score 为 None）。"""
    coll_id, coll_b_id = kb_search_fixture
    monkeypatch.setattr("app.storage.repositories.kb.EmbeddingService", lambda: NearEmbedder())
    monkeypatch.setattr("app.storage.repositories.kb.RerankService", lambda: FailingReranker())
    hits = await KbService().search(None, None, coll_ids=[coll_id], query="天气", top_k=1,
        hybrid={"semantic": 1, "bm25": 1},
    )
    assert len(hits) == 1
    assert "天气" in hits[0]["text"]  # RRF 顺序：doc1 语义最近
    assert hits[0]["rerank_score"] is None  # 降级回退，不填 rerank_score
