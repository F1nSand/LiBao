"""T8 kb_search 内置工具测试（文件化）：注册/ACI、org 上下文、handler 融合结果、
executor 全路径、参数校验、org 缺失降级。
"""
from __future__ import annotations

import uuid

import pytest

from app.storage.file.store import get_store
from app.storage.models.kb import KbChunk
from app.storage.repositories.bm25 import BM25Index
from app.storage.repositories.kb import KbRepository
from app.tools import executor
from app.tools.builtin import register_builtin_tools
from app.tools.context import set_tool_org
from app.tools.registry import get, get_by_name


@pytest.fixture
async def kb_tool_fixture(clean_mcp_specs):
    register_builtin_tools()
    store = get_store()
    store.bm25 = BM25Index()
    repo = KbRepository()
    uid = uuid.uuid4().hex[:8]
    coll = await repo.create_collection(uuid.UUID(int=0), f"kb-{uid}", 512, 64)
    doc = await repo.create_document(
        collection_id=coll.id, org_id=uuid.UUID(int=0), filename="指南.txt",
        content_type="text/plain", size_bytes=10, content="知识库里有关于天气的记录。",
    )
    doc.status = "indexed"
    index = await repo._load_index(coll.id)  # noqa: SLF001
    index["documents"][str(doc.id)] = doc.to_dict()
    await repo._save_index(coll.id, index)  # noqa: SLF001
    await repo.insert_chunks(
        [
            KbChunk(
                document_id=doc.id, collection_id=coll.id, org_id=uuid.UUID(int=0),
                chunk_index=0, content="知识库里有关于天气的记录。", embedding=[0.5] * 1024,
            )
        ]
    )
    yield coll.id


async def test_registered_with_aci(kb_tool_fixture):
    spec = get("tl_kb_search")
    assert spec is not None
    assert spec.name == "kb_search"
    assert spec.enabled is True
    assert spec.builtin is True
    aci = spec.aci()
    props = aci["function"]["parameters"]["properties"]
    assert "query" in props
    assert "collection_ids" in props


async def test_handler_returns_fused_results(kb_tool_fixture, monkeypatch):
    coll_id = kb_tool_fixture

    class NearEmbedder:
        async def embed_query(self, text):
            return [0.5] * 1024

    monkeypatch.setattr("app.storage.repositories.kb.EmbeddingService", lambda: NearEmbedder())
    set_tool_org(str(coll_id))
    try:
        spec = get("tl_kb_search")
        result = await executor.execute(spec, {"query": "天气"})
        assert result.ok is True
        assert result.output["count"] >= 1
        assert "天气" in result.output["results"][0]["text"]
    finally:
        set_tool_org(None)


async def test_missing_org_context_uses_default(kb_tool_fixture):
    """org 折叠：无上下文时用默认 org（不再降级 error）。"""
    _ = kb_tool_fixture  # fixture 建数据（coll_id 无需解包）
    spec = get("tl_kb_search")
    result = await executor.execute(spec, {"query": "天气"})  # 无 org 上下文
    assert result.ok is True
    assert result.output["count"] >= 1


async def test_executor_validation_failure(kb_tool_fixture):
    spec = get("tl_kb_search")
    result = await executor.execute(spec, {})  # 缺 query
    assert result.ok is False
    assert "参数校验失败" in result.error


async def test_registration_idempotent(kb_tool_fixture):
    register_builtin_tools()  # 幂等引导
    assert get_by_name("kb_search") is not None
