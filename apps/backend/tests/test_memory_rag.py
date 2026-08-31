"""P2 全局记忆 RAG 测试：卡片↔向量三点同步、语义检索命中、embedding 故障回退 importance、
工作区作用域过滤、memory_inject 语义检索路径。"""
from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import HumanMessage

from app.core.embeddings import EmbeddingService
from app.orchestration.nodes.memory_inject import _last_user_text, memory_inject_node
from app.storage.models.memory import LongTermMemory
from app.storage.repositories.memory import MemoryRepository
from app.storage.repositories.memory_vectors import reset_memory_lance


@pytest.fixture(autouse=True)
def _reset_lance():
    reset_memory_lance()
    yield
    reset_memory_lance()


class DictEmbedder:
    """按 query 关键词映射正交向量（确定性：写入与检索共用同一映射）。

    注意：常数向量（如 [0.9]*1024）归一化后同方向、余弦恒为 1.0 无法排序；
    用第 0/1 维独热正交向量（余弦 1.0 / 0.0 可判别）。
    """

    def __init__(self) -> None:
        self._coffee = [1.0] + [0.0] * 1023
        self._stock = [0.0, 1.0] + [0.0] * 1022

    async def embed_query(self, text: str) -> list[float]:
        if "咖啡" in text:
            return self._coffee
        if "股票" in text:
            return self._stock
        return [0.0] * 1024


@pytest.fixture
def fixed_embedder(monkeypatch):
    """替换 EmbeddingService.embed_query：咖啡→e0，股票→e1，其余零向量。"""
    embedder = DictEmbedder()

    async def fake_embed(self, text: str) -> list[float]:
        return await embedder.embed_query(text)

    monkeypatch.setattr(EmbeddingService, "embed_query", fake_embed)
    return embedder


async def _mk_card(user_id: uuid.UUID, title: str, text: str, *, ws: uuid.UUID | None = None) -> LongTermMemory:
    repo = MemoryRepository()
    return await repo.create_card(
        user_id=user_id, card_type="note", content={"text": text}, title=title,
        importance=0.5, workspace_id=ws,
    )


async def test_create_card_syncs_vector_and_search_hits(fixed_embedder):
    uid = uuid.UUID(int=1)
    card = await _mk_card(uid, "喝咖啡", "用户喜欢喝咖啡")
    hits = await MemoryRepository().semantic_search(uid, "我想喝一杯咖啡", limit=5)
    assert [str(h.id) for h in hits] == [str(card.id)]


async def test_search_ranks_semantic_before_others(fixed_embedder):
    """语义命中优先：无关卡（importance 更高）排在语义相关卡之后。"""
    uid = uuid.UUID(int=1)
    far = await _mk_card(uid, "股票", "用户关注股票市场")
    far.importance = 0.9  # 高 importance 但不相关
    near = await _mk_card(uid, "咖啡", "用户喜欢喝咖啡")
    hits = await MemoryRepository().semantic_search(uid, "喝咖啡怎么样", limit=5)
    assert [str(h.id) for h in hits] == [str(near.id), str(far.id)]


async def test_embedding_failure_falls_back_to_importance(monkeypatch):
    """embedding 故障 → 回退 importance 排序（原行为保底）。"""
    async def boom(self, text: str):
        raise RuntimeError("embedding API down")

    monkeypatch.setattr(EmbeddingService, "embed_query", boom)
    uid = uuid.UUID(int=1)
    low = await _mk_card(uid, "低", "低重要性内容")
    low.importance = 0.2
    high = await _mk_card(uid, "高", "高重要性内容")
    high.importance = 0.9
    hits = await MemoryRepository().semantic_search(uid, "任意查询", limit=5)
    assert [str(h.id) for h in hits] == [str(high.id), str(low.id)]


async def test_empty_query_falls_back_to_importance():
    uid = uuid.UUID(int=1)
    low = await _mk_card(uid, "低", "低")
    low.importance = 0.2
    high = await _mk_card(uid, "高", "高")
    high.importance = 0.9
    hits = await MemoryRepository().semantic_search(uid, "  ", limit=5)
    assert [str(h.id) for h in hits] == [str(high.id), str(low.id)]


async def test_soft_delete_removes_vector(fixed_embedder):
    uid = uuid.UUID(int=1)
    card = await _mk_card(uid, "咖啡", "用户喜欢喝咖啡")
    await MemoryRepository().soft_delete(card)
    hits = await MemoryRepository().semantic_search(uid, "喝咖啡", limit=5)
    assert hits == []  # 向量已删 + 卡片软删双过滤


async def test_version_update_refreshes_vector(fixed_embedder):
    """add_version 内容变更 → 向量更新（语义距离向新主题靠近）。"""
    from app.storage.repositories.memory_vectors import search as _vec_search

    uid = uuid.UUID(int=1)
    card = await _mk_card(uid, "咖啡", "用户喜欢喝咖啡")
    await MemoryRepository().add_version(card, {"text": "用户关注股票市场"}, 0.9)
    stock_vec = [0.0, 1.0] + [0.0] * 1022
    coffee_vec = [1.0] + [0.0] * 1023
    stock_hits = await _vec_search(str(uid), stock_vec, limit=5)
    coffee_hits = await _vec_search(str(uid), coffee_vec, limit=5)
    assert stock_hits[0][0] == str(card.id)
    assert stock_hits[0][1] < coffee_hits[0][1]  # 更新后更贴近股票语义（距离更近）


async def test_workspace_scope_filter(fixed_embedder):
    """作用域：普通会话只出全局；工作区会话 = 项目 ∪ 全局。"""
    uid = uuid.UUID(int=1)
    ws = uuid.UUID(int=2)
    global_card = await _mk_card(uid, "咖啡", "用户喜欢喝咖啡")
    project_card = await _mk_card(uid, "项目架构", "项目计划用股票分析模块", ws=ws)
    # 普通会话 → 只全局
    hits = await MemoryRepository().semantic_search(uid, "咖啡 FastAPI", limit=5)
    assert [str(h.id) for h in hits] == [str(global_card.id)]
    # 工作区会话 → 项目 ∪ 全局（语义按 query 命中）
    hits = await MemoryRepository().semantic_search(uid, "咖啡 FastAPI", workspace_id=ws, limit=5)
    assert {str(h.id) for h in hits} == {str(global_card.id), str(project_card.id)}


async def test_last_user_text_extraction():
    msgs = [HumanMessage(content="历史问题"), HumanMessage(content="我的偏好是喝咖啡")]
    assert _last_user_text(msgs) == "我的偏好是喝咖啡"
    assert _last_user_text([]) == ""


async def test_memory_inject_uses_semantic_search(fixed_embedder, monkeypatch):
    """memory_inject 走语义检索（semantic_search 被调用，query = 最后 user 消息）。"""
    uid = uuid.UUID(int=1)
    card = await _mk_card(uid, "咖啡", "用户喜欢喝咖啡")
    called: list[str] = []

    async def fake_search(self, user_id, query, *, workspace_id=None, limit=5):
        called.append(query)
        rows = await self.table.list(
            filter_fn=lambda c: c.id == card.id and c.deleted_at is None, limit=limit
        )
        return rows

    monkeypatch.setattr(MemoryRepository, "semantic_search", fake_search)
    state = {
        "user_id": str(uid),
        "messages": [HumanMessage(content="历史"), HumanMessage(content="今天想喝咖啡")],
        "agent_config": {"workspace_id": None},
        "run_logs": [],
    }
    result = await memory_inject_node(state, {"configurable": {"trace_id": "t1"}})
    assert called == ["今天想喝咖啡"]
    assert result["memory_refs"][0]["title"] == "咖啡"
    logs = result.get("run_logs") or []
    assert any(log.get("type") == "memory" for log in logs)
