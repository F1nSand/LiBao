"""T8 kb_search 内置工具测试（DB-backed）：注册/ACI、org 上下文、handler 融合结果、
executor 全路径、参数校验、org 缺失降级。
"""
from __future__ import annotations

import uuid

import pytest

from app.core.security import hash_password
from app.storage.db import init_db, set_sessionmaker
from app.storage.file.store import get_store
from app.storage.models import KbChunk, KbCollection, KbDocument, Org, User
from app.tools import executor
from app.tools.builtin import register_builtin_tools
from app.tools.context import set_tool_org
from app.tools.registry import get, get_by_name
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def kb_tool_fixture(clean_mcp_specs):
    register_builtin_tools()
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-kbt-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"kbt_{uid}", password_hash=hash_password("x"), name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        coll = KbCollection(org_id=org.id, name=f"kb-{uid}")
        session.add(coll)
        await session.flush()
        doc = KbDocument(
            collection_id=coll.id, org_id=org.id, filename="指南.txt", content_type="text/plain",
            size_bytes=10, content="知识库里有关于天气的记录。", status="indexed",
        )
        session.add(doc)
        await session.flush()
        session.add(
            KbChunk(
                document_id=doc.id, collection_id=coll.id, org_id=org.id, chunk_index=0,
                content="知识库里有关于天气的记录。", embedding=[0.5] * 1024,
            )
        )
        await session.commit()
    set_sessionmaker(sessionmaker)
    yield sessionmaker, user, org.id, coll.id
    set_sessionmaker(None)
    await engine.dispose()


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
    sessionmaker, user, org_id, coll_id = kb_tool_fixture

    class NearEmbedder:
        async def embed_query(self, text):
            return [0.5] * 1024

    monkeypatch.setattr("app.storage.repositories.kb.EmbeddingService", lambda: NearEmbedder())
    set_tool_org(str(org_id))
    try:
        spec = get("tl_kb_search")
        result = await executor.execute(spec, {"query": "天气"})
        assert result.ok is True
        assert result.output["count"] >= 1
        assert "天气" in result.output["results"][0]["text"]
    finally:
        set_tool_org(None)


async def test_missing_org_context_degrades(kb_tool_fixture):
    sessionmaker, user, org_id, coll_id = kb_tool_fixture
    spec = get("tl_kb_search")
    result = await executor.execute(spec, {"query": "天气"})  # 无 org 上下文
    assert result.ok is True  # 不报错（降级结果）
    assert "error" in result.output


async def test_executor_validation_failure(kb_tool_fixture):
    spec = get("tl_kb_search")
    result = await executor.execute(spec, {})  # 缺 query
    assert result.ok is False
    assert "参数校验失败" in result.error


async def test_registration_idempotent(kb_tool_fixture):
    register_builtin_tools()  # 幂等引导
    assert get_by_name("kb_search") is not None
