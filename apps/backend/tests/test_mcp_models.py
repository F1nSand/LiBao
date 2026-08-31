"""mcp_servers 模型测试（文件化）：行注册/读回、默认 enabled、软删列、Settings/错误码。"""
from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.core.errors import (
    ERR_MCP_CONNECT,
    ERR_MCP_NAME_CONFLICT,
    ERR_MCP_SERVER_NOT_FOUND,
    ERR_TOOL_NOT_FOUND,
)
from app.storage.file.store import get_store
from app.storage.models import McpServer
from app.storage.models.mcp_server import McpServer as McpServerDirect
from app.storage.repositories.mcp_server import McpServerRepository


async def test_mcp_server_row_roundtrip():
    org_id = uuid.uuid4()
    repo = McpServerRepository()
    row = repo.create(
        org_id=org_id,
        name="demo",
        transport="stdio",
        command="python demo.py",
        url=None,
        headers=None,
        enabled=True,
    )
    await get_store().table("mcp_servers").flush()
    got = await repo.get_by_id_including_deleted(row.id)
    assert got is not None
    assert got.name == "demo"
    assert got.transport == "stdio"
    assert got.headers is None
    assert got.url is None
    assert got.enabled is True
    assert got.deleted_at is None  # Row 软删列


async def test_mcp_server_http_row_with_headers():
    org_id = uuid.uuid4()
    repo = McpServerRepository()
    row = repo.create(
        org_id=org_id,
        name="httpd",
        transport="http",
        command=None,
        url="https://demo.mcp.local/mcp",
        headers={"Authorization": "Bearer x"},
        enabled=False,
    )
    await get_store().table("mcp_servers").flush()
    got = await repo.get_by_id_including_deleted(row.id)
    assert got.transport == "http"
    assert got.url == "https://demo.mcp.local/mcp"
    assert got.headers == {"Authorization": "Bearer x"}
    assert got.enabled is False


async def test_mcp_server_exported_from_models_package():
    # __init__.py 统一出口导出（类名与模块路径保持一致）
    assert McpServer is McpServerDirect


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
