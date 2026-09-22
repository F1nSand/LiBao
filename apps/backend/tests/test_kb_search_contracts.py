import uuid

from app.services.kb import KbService
from app.storage.repositories.kb import KbRepository


async def test_top_k_clamps_to_ten(monkeypatch):
    chunk_ids = [uuid.uuid4() for _ in range(12)]
    requested_top_n = []

    class Embedder:
        async def embed_query(self, query):
            return [0.0] * 1024

    async def semantic_search(self, org_id, collection_ids, query_vec, limit=50):
        return [(chunk_id, f"result {i}", 0.0) for i, chunk_id in enumerate(chunk_ids)]

    async def chunk_sources(self, ids):
        return {str(chunk_id): {} for chunk_id in ids}

    class CaptureRerankFailure:
        async def rerank(self, query, documents, top_n):
            requested_top_n.append(top_n)
            raise RuntimeError("rerank disabled in test")

    monkeypatch.setattr(KbRepository, "semantic_search", semantic_search)
    monkeypatch.setattr(KbRepository, "chunk_sources", chunk_sources)
    monkeypatch.setattr("app.storage.repositories.kb.EmbeddingService", Embedder)
    monkeypatch.setattr("app.storage.repositories.kb.RerankService", CaptureRerankFailure)

    hits = await KbService().search(
        None,
        None,
        coll_ids=[],
        query="query",
        top_k=25,
        hybrid={"semantic": 1, "bm25": 0},
    )

    assert len(hits) == 10
    assert requested_top_n == [10]
