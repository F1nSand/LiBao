"""T5 启动重建测试（DB-backed）：sync_registry_from_db 从 DB 重建 MCP spec。

覆盖：重建 spec + enabled 跟随、raw 工具名透传（mcp_tool_name）、server 软删 → 禁用、
server 停用 → 工具禁用、同步幂等。
"""
from __future__ import annotations

import socket
import uuid

import pytest

from app.core.security import hash_password
from app.services.tool import ToolService
from app.storage.db import init_db
from app.storage.models import Org, User
from app.storage.models.mcp_server import McpServer
from app.storage.repositories.mcp_server import McpServerRepository
from app.storage.repositories.tool_definition import ToolDefinitionRepository
from app.tools import executor
from app.tools.builtin import register_builtin_tools
from app.tools.mcp_manager import manager as mcp_manager
from app.tools.registry import all_tools, get, get_by_name, unregister


def _db_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 5432), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="Docker db 未运行")


@pytest.fixture
async def sync_fixture(monkeypatch):
    register_builtin_tools()
    # 进程级 registry：setup 幂等清理历史 MCP spec（async teardown 延迟执行，不可靠）
    for spec in [s for s in all_tools() if s.id.startswith("mc_")]:
        unregister(spec.id)
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-mcpsync-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"mcpsync_{uid}", password_hash=hash_password("x"), name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        # 直接构造：server + 工具行（绕开 register，模拟"注册过但进程重启"）
        server = McpServerRepository(session).create(
            org_id=org.id, name="demo", transport="stdio", command="python demo.py",
            url=None, headers=None, enabled=True,
        )
        session.add(server)
        await session.flush()
        repo = ToolDefinitionRepository(session)
        for name, raw in (("echo", "Echo!"), ("add", "add")):
            row = await repo.create(
                org_id=org.id, name=name, description="d", params_schema={},
                tool_type="execution", enabled=True, mcp_source=f"mcp:{server.id}", mcp_tool_name=raw,
            )
            session.add(row)
        await session.commit()
    yield sessionmaker, org.id
    await engine.dispose()


async def test_sync_rebuilds_mcp_spec_and_uses_raw_name(sync_fixture, monkeypatch):
    sessionmaker, org_id = sync_fixture
    captured: dict = {}

    async def fake_call(server_id, cfg, tool_name, args):
        captured.update(server_id=server_id, tool_name=tool_name)
        return True, "ok"

    monkeypatch.setattr(mcp_manager, "call", fake_call)
    async with sessionmaker() as session:
        await ToolService().sync_registry_from_db(session, org_id)
    spec = get("mc_demo_echo")
    assert spec is not None  # 重建
    assert spec.enabled is True  # enabled 跟随 DB
    # 执行路径走真 executor → handler → manager.call（raw 名透传）
    result = await executor.execute(spec, {})
    assert result.ok is True
    assert result.output == "ok"
    assert captured["tool_name"] == "Echo!"  # 原始 MCP 工具名（非 slug）


async def test_sync_respects_row_enabled_false(sync_fixture, monkeypatch):
    sessionmaker, org_id = sync_fixture
    async with sessionmaker() as session:
        # 停用 echo 行（sync 前 spec 未注册，直接 repo 查）
        row = await ToolDefinitionRepository(session).get_by_org_name(org_id, "echo")
        row.enabled = False
        await session.commit()
        await ToolService().sync_registry_from_db(session, org_id)
    assert get("mc_demo_echo").enabled is False
    assert get("mc_demo_add").enabled is True


async def test_sync_disables_spec_for_deleted_server(sync_fixture, monkeypatch):
    sessionmaker, org_id = sync_fixture
    async with sessionmaker() as session:
        # 模拟不一致状态：server 软删但工具行仍在 → 工具 spec 禁用（源不可用）
        server = await McpServerRepository(session).get_by_org_name(org_id, "demo")
        await McpServerRepository(session).soft_delete(server)
        await session.commit()
        await ToolService().sync_registry_from_db(session, org_id)
    spec = get("mc_demo_echo")
    assert spec is not None
    assert spec.enabled is False


async def test_sync_disables_spec_for_disabled_server(sync_fixture, monkeypatch):
    sessionmaker, org_id = sync_fixture
    async with sessionmaker() as session:
        server = await McpServerRepository(session).get_by_org_name(org_id, "demo")
        server.enabled = False
        await session.commit()
        await ToolService().sync_registry_from_db(session, org_id)
    assert get("mc_demo_echo").enabled is False


async def test_sync_idempotent_no_double_register(sync_fixture):
    sessionmaker, org_id = sync_fixture
    async with sessionmaker() as session:
        await ToolService().sync_registry_from_db(session, org_id)
        await ToolService().sync_registry_from_db(session, org_id)  # 第二次不得 ValueError（id 冲突）
    assert get_by_name("echo") is not None
