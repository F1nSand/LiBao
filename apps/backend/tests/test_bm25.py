"""BM25 索引测试：space_cjk 分词 golden + top-k 顺序断言。"""
from __future__ import annotations

import uuid

from app.storage.repositories.bm25 import BM25Index, _tokenize
from app.storage.repositories.kb import space_cjk


def test_space_cjk_inserts_spaces():
    assert space_cjk("天气很好") == "天 气 很 好 "
    assert space_cjk("hello天气") == "hello天 气 "


def test_tokenize_matches_tsvector_semantics():
    assert _tokenize("今天天气很好") == ["今", "天", "天", "气", "很", "好"]
    assert _tokenize("Hello World") == ["hello", "world"]


async def test_bm25_rank_order():
    idx = BM25Index()
    cid_a = str(uuid.uuid4())
    cid_b = str(uuid.uuid4())
    idx.rebuild(
        [
            (cid_a, "今天天气很好适合散步", "coll1"),
            (cid_b, "股票市场今天大涨", "coll1"),
        ]
    )
    hits = idx.search("天气", limit=10)
    assert hits[0][0] == cid_a  # 天气在 a 中出现 2 次 → 分数更高
    assert hits[0][2] > hits[1][2]


async def test_bm25_collection_filter():
    idx = BM25Index()
    cid_a = str(uuid.uuid4())
    cid_b = str(uuid.uuid4())
    idx.rebuild(
        [
            (cid_a, "天气查询专用", "collA"),
            (cid_b, "天气查询专用", "collB"),
        ]
    )
    hits = idx.search("天气", collection_ids=["collA"], limit=10)
    assert [h[0] for h in hits] == [cid_a]


async def test_bm25_empty_query_and_empty_corpus():
    idx = BM25Index()
    assert idx.search("") == []
    idx.rebuild([])
    assert idx.size == 0
    assert idx.search("天气") == []
