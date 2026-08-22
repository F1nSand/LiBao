"""T2 工具服务层测试：tl_ id 派生、默认关闭、重名 40903、启停同步桥、search、软删。

需要 Docker db（localhost:5432）；DB 不可达自动跳过。
"""
from __future__ import annotations

import uuid

import pytest

from app.api.schemas.tools import CreateToolRequest
from app.core.errors import AppError
from app.core.security import hash_password
from app.orchestration.context_builder import acis_for_tools
from app.services.serializers import serialize_tool_definition
from app.services.tool import ToolService
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import Org, User
from app.tools.builtin import register_builtin_tools
from app.tools.registry import get, set_enabled
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def tool_fixture():
    register_builtin_tools()
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-tools-{uid}")
        session.add(org)
        await session.flush()
        user = User(
            username=f"tools_{uid}", password_hash=hash_password("x"), name="T", role="admin", org_id=org.id
        )
        session.add(user)
        await session.commit()
    yield sessionmaker, user
    await engine.dispose()


async def test_create_tool_default_disabled(tool_fixture):
    sessionmaker, user = tool_fixture
    async with get_store().session(sessionmaker) as session:
        row = await ToolService().create(session, user, CreateToolRequest(name="stock_query", tool_type="perception"))
        data = serialize_tool_definition(row)
        assert data["id"] == "tl_stock_query"  # tl_ 前缀派生
        assert data["enabled"] is False  # 默认关闭


async def test_create_duplicate_name_conflict(tool_fixture):
    sessionmaker, user = tool_fixture
    async with get_store().session(sessionmaker) as session:
        await ToolService().create(session, user, CreateToolRequest(name="stock_query"))
        with pytest.raises(AppError) as exc:
            await ToolService().create(session, user, CreateToolRequest(name="stock_query"))
        assert exc.value.code == 40903


async def test_builtin_time_now_serializes_with_registry_id(tool_fixture):
    sessionmaker, user = tool_fixture
    async with get_store().session(sessionmaker) as session:
        row = await ToolService().create(session, user, CreateToolRequest(name="time_now"))
        assert serialize_tool_definition(row)["id"] == "tl_time_now"  # 与 registry spec.id 一致


async def test_set_enabled_syncs_registry(tool_fixture):
    sessionmaker, user = tool_fixture
    async with get_store().session(sessionmaker) as session:
        await ToolService().create(session, user, CreateToolRequest(name="time_now"))
        await ToolService().set_enabled(session, user, "tl_time_now", enabled=True)
        assert get("tl_time_now").enabled is True
        assert len(acis_for_tools(["tl_time_now"])) == 1  # 启用 → ACI 出现
        await ToolService().set_enabled(session, user, "tl_time_now", enabled=False)
        assert get("tl_time_now").enabled is False
        assert acis_for_tools(["tl_time_now"]) == []  # 停用 → ACI 消失（默认关闭原则生效）
    # 恢复现场
    set_enabled("tl_time_now", True)


async def test_search_case_insensitive(tool_fixture):
    sessionmaker, user = tool_fixture
    async with get_store().session(sessionmaker) as session:
        await ToolService().create(session, user, CreateToolRequest(name="StockQuery", description="股票查询工具"))
        hits = await ToolService().search(session, user.org_id, "stock")
        assert any(h["name"] == "StockQuery" for h in hits)
        hits2 = await ToolService().search(session, user.org_id, "STOCK")
        assert len(hits2) == len(hits)


async def test_soft_delete(tool_fixture):
    sessionmaker, user = tool_fixture
    async with get_store().session(sessionmaker) as session:
        await ToolService().create(session, user, CreateToolRequest(name="time_now"))
        await ToolService().soft_delete(session, user, "tl_time_now")
        with pytest.raises(AppError) as exc:
            await ToolService().get_in_org(session, user.org_id, "tl_time_now")
        assert exc.value.code == 40405
        assert get("tl_time_now").enabled is False  # 删除即停用（同步桥）
    set_enabled("tl_time_now", True)


async def test_serialize_meta_flag(tool_fixture):
    """M7 前：serialize_tool_definition 带 meta（元工具标记，前端工具页区分）。"""
    sessionmaker, user = tool_fixture
    async with get_store().session(sessionmaker) as session:
        row = await ToolService().create(session, user, CreateToolRequest(name="time_now"))
        assert serialize_tool_definition(row)["meta"] is False  # 常规工具
        row2 = await ToolService().create(session, user, CreateToolRequest(name="kb_search"))
        assert serialize_tool_definition(row2)["meta"] is True  # 元工具


async def test_search_excludes_meta_tools(tool_fixture):
    """M7 前：/tools/search 排除 meta 工具（tool_search/kb_search 平台发现层不自发现）。"""
    sessionmaker, user = tool_fixture
    async with get_store().session(sessionmaker) as session:
        await ToolService().create(session, user, CreateToolRequest(name="kb_search"))
        await ToolService().create(session, user, CreateToolRequest(name="kb_query_regular", description="检索"))
        hits = await ToolService().search(session, user.org_id, "kb")
        names = {h["name"] for h in hits}
        assert "kb_search" not in names  # meta 工具排除
        assert "kb_query_regular" in names  # 常规工具保留
