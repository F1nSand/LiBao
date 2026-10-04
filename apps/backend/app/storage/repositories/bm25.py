"""Legacy degraded-mode BM25 fallback kept for one compatibility release.

Healthy runtime retrieval uses persistent LanceDB FTS. This in-memory index is rebuilt once
at startup only when a v1 document could not be migrated; write paths update it only in that
explicit degraded mode.

- IDF 覆写为恒正平滑（原 BM25Okapi 的 log(N-df+0.5)-log(df+0.5) 对常见词为负 → 负分时
  高频词反而分更低，中文常见词场景排序反转；+1 平滑恒正，与 ts_rank 行为一致）。
"""

from __future__ import annotations

import logging
import math

from rank_bm25 import BM25Okapi

from app.storage.repositories.kb import space_cjk

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """plainto_tsquery('simple') 语义 ≈ 全小写 + 空格分词；space_cjk 逐字插空格对齐 tsvector unigram。"""
    return space_cjk(text).lower().split()


class _BM25OkapiPos(BM25Okapi):
    """BM25Okapi 子类：IDF 恒正平滑（log(1 + (N-df+0.5)/(df+0.5))），防负分排序反转。"""

    def _calc_idf(self, nd: dict) -> None:
        for word, freq in nd.items():
            self.idf[word] = math.log(1 + (self.corpus_size - freq + 0.5) / (freq + 0.5))


class BM25Index:
    """内存 BM25 索引：语料 (chunk_id, text, collection_id) + BM25OkapiPos 打分。"""

    def __init__(self) -> None:
        self._ids: list[str] = []
        self._texts: dict[str, str] = {}
        self._collections: dict[str, str] = {}
        self._bm25: _BM25OkapiPos | None = None

    def rebuild(self, chunks: list[tuple[str, str, str]]) -> None:
        """全量重建：chunks = [(chunk_id, content, collection_id)]。"""
        self._ids = [cid for cid, _, _ in chunks]
        self._texts = {cid: text for cid, text, _ in chunks}
        self._collections = {cid: coll for cid, _, coll in chunks}
        corpus = [_tokenize(text) for _, text, _ in chunks]
        self._bm25 = _BM25OkapiPos(corpus) if corpus else None

    @property
    def size(self) -> int:
        return len(self._ids)

    def search(
        self, query: str, collection_ids: list[str] | None = None, limit: int = 50
    ) -> list[tuple[str, str, float]]:
        """BM25 打分降序，返回 (chunk_id, content, score)。collection_ids 空 = 全量。"""
        if self._bm25 is None or not query.strip():
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(zip(self._ids, scores, strict=True), key=lambda kv: -kv[1])
        out: list[tuple[str, str, float]] = []
        for cid, score in ranked:
            if score == 0:
                break  # 无共同词（恒 0 分）→ 后续全 0
            if collection_ids and self._collections.get(cid) not in collection_ids:
                continue
            out.append((cid, self._texts[cid], float(score)))
            if len(out) >= limit:
                break
        return out
