"""T1 mcp_servers 模型测试：行落库/读回、默认 enabled、软删列、Settings/错误码。

需要 Docker db（localhost:5432）；DB 不可达自动跳过。
"""
from __future__ import annotations

import uuid

import pytest

from app.core.config import get_settings
from app.core.errors import (
    ERR_MCP_CONNECT,
    ERR_MCP_NAME_CONFLICT,
    ERR_MCP_SERVER_NOT_FOUND,
    ERR_TOOL_NOT_FOUND,
)
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import McpServer, Org
from app.storage.models.mcp_server import McpServer as McpServerDirect
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def mcp_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-mcp-{uid}")
        session.add(org)
        await session.commit()
        org_id = org.id
    yield sessionmaker, org_id
    await engine.dispose()


async def test_mcp_server_row_roundtrip(mcp_fixture):
    sessionmaker, org_id = mcp_fixture
    async with get_store().session(sessionmaker) as session:
        row = McpServer(
            org_id=org_id,
            name="demo",
            transport="stdio",
            command="python demo.py",
            url=None,
            headers=None,
            enabled=True,
        )
        session.add(row)
        await session.commit()
        got = await session.get(McpServer, row.id)
        assert got is not None
        assert got.name == "demo"
        assert got.transport == "stdio"
        assert got.headers is None
        assert got.url is None
        assert got.enabled is True
        assert got.deleted_at is None  # BaseModel 软删列


async def test_mcp_server_http_row_with_headers(mcp_fixture):
    sessionmaker, org_id = mcp_fixture
    async with get_store().session(sessionmaker) as session:
        row = McpServer(
            org_id=org_id,
            name="httpd",
            transport="http",
            command=None,
            url="https://demo.mcp.local/mcp",
            headers={"Authorization": "Bearer x"},
            enabled=False,
        )
        session.add(row)
        await session.commit()
        got = await session.get(McpServer, row.id)
        assert got.transport == "http"
        assert got.url == "https://demo.mcp.local/mcp"
        assert got.headers == {"Authorization": "Bearer x"}
        assert got.enabled is False


async def test_mcp_server_exported_from_models_package(mcp_fixture):
    # __init__.py 统一出口导出（FK 字符串配置期解析依赖全量 mapper 导入）
    assert McpServer is McpServerDirect
    assert McpServer.__tablename__ == "mcp_servers"


def test_settings_mcp_fields():
    s = get_settings()
    assert s.mcp_breaker_threshold == 3
    assert s.mcp_breaker_cooldown_s == 60
    assert s.aci_full_limit == 30


def test_mcp_error_codes_registered():
    # 新增段位：404xx 未找到 / 409xx 冲突 / 500xx 服务器；60003 既有熔断码
    assert ERR_MCP_SERVER_NOT_FOUND == 40406
    assert ERR_MCP_NAME_CONFLICT == 40904
    assert ERR_MCP_CONNECT == 50201
    assert ERR_TOOL_NOT_FOUND == 40405  # 邻近码不漂移
