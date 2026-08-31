"""T5 启动重建测试（文件存储）：sync_registry_from_file 从 tool_definitions.json 重建 MCP spec。

覆盖：重建 spec + enabled 跟随、raw 工具名透传（mcp_tool_name）、server 软删 → 禁用、
server 停用 → 工具禁用、同步幂等、全量 sync 覆盖所有行（I5）。
工具名随机化：全量 sync 遍历全表行，残留测试行的同名工具会干扰断言。
"""
from __future__ import annotations

import uuid

import pytest

from app.services.tool import ToolService
from app.storage.constants import DEFAULT_ORG_ID
from app.storage.file.store import get_store
from app.storage.repositories.mcp_server import McpServerRepository
from app.storage.repositories.tool_definition import ToolDefinitionRepository
from app.tools import executor
from app.tools.mcp_manager import manager as mcp_manager
from app.tools.registry import get, get_by_name


@pytest.fixture
async def sync_fixture(clean_mcp_specs):
    uid = uuid.uuid4().hex[:8]
    tool_a, tool_b = f"echo_{uid}", f"add_{uid}"
    server_name = f"demo_{uid}"
    async with get_store().session() as session:
        # 直接构造：server + 工具行（绕开 register，模拟"注册过但进程重启"）
        server = McpServerRepository().create(
            org_id=DEFAULT_ORG_ID, name=server_name, transport="stdio", command="python demo.py",
            url=None, headers=None, enabled=True,
        )
        repo = ToolDefinitionRepository()
        for name, raw in ((tool_a, "Echo!"), (tool_b, "add")):
            await repo.create(
                org_id=DEFAULT_ORG_ID, name=name, description="d", params_schema={},
                tool_type="execution", enabled=True, mcp_source=f"mcp:{server.id}", mcp_tool_name=raw,
            )
        await session.commit()
    yield DEFAULT_ORG_ID, server_name, tool_a, tool_b


async def test_sync_rebuilds_mcp_spec_and_uses_raw_name(sync_fixture, monkeypatch):
    org_id, server_name, tool_a, tool_b = sync_fixture
    captured: dict = {}

    async def fake_call(server_id, cfg, tool_name, args):
        captured.update(server_id=server_id, tool_name=tool_name)
        return True, "ok"

    monkeypatch.setattr(mcp_manager, "call", fake_call)
    async with get_store().session():
        await ToolService().sync_registry_from_file()
    spec_id = f"mc_{server_name}_{tool_a}"
    spec = get(spec_id)
    assert spec is not None  # 重建
    assert spec.enabled is True  # enabled 跟随 DB
    # 执行路径走真 executor → handler → manager.call（raw 名透传）
    result = await executor.execute(spec, {})
    assert result.ok is True
    assert result.output == "ok"
    assert captured["tool_name"] == "Echo!"  # 原始 MCP 工具名（非 slug）


async def test_sync_respects_row_enabled_false(sync_fixture, monkeypatch):
    org_id, server_name, tool_a, tool_b = sync_fixture
    async with get_store().session() as session:
        # 停用 tool_a 行（sync 前 spec 未注册，直接 repo 查）
        row = await ToolDefinitionRepository().get_by_org_name(org_id, tool_a)
        row.enabled = False
        await session.commit()
        await ToolService().sync_registry_from_file()
    assert get(f"mc_{server_name}_{tool_a}").enabled is False
    assert get(f"mc_{server_name}_{tool_b}").enabled is True


async def test_sync_disables_spec_for_deleted_server(sync_fixture, monkeypatch):
    org_id, server_name, tool_a, tool_b = sync_fixture
    async with get_store().session() as session:
        # 模拟不一致状态：server 软删但工具行仍在 → 工具 spec 禁用（源不可用）
        server = await McpServerRepository().get_by_org_name(org_id, server_name)
        await McpServerRepository().soft_delete(server)
        await session.commit()
        await ToolService().sync_registry_from_file()
    spec = get(f"mc_{server_name}_{tool_a}")
    assert spec is not None
    assert spec.enabled is False


async def test_sync_disables_spec_for_disabled_server(sync_fixture, monkeypatch):
    org_id, server_name, tool_a, tool_b = sync_fixture
    async with get_store().session() as session:
        server = await McpServerRepository().get_by_org_name(org_id, server_name)
        server.enabled = False
        await session.commit()
        await ToolService().sync_registry_from_file()
    assert get(f"mc_{server_name}_{tool_a}").enabled is False


async def test_sync_idempotent_no_double_register(sync_fixture):
    org_id, server_name, tool_a, tool_b = sync_fixture
    async with get_store().session():
        await ToolService().sync_registry_from_file()
        await ToolService().sync_registry_from_file()  # 第二次不得 ValueError（id 冲突）
    assert get_by_name(tool_a) is not None


async def test_sync_full_scope_rebuilds_all_orgs(sync_fixture):
    # I5：全量 sync 重建所有行的 MCP spec（org 折叠后仍按全表遍历，其他 org 行不失效）
    org_id, server_name, tool_a, tool_b = sync_fixture
    uid2 = uuid.uuid4().hex[:8]
    server2_name, tool2 = f"other_{uid2}", f"ping_{uid2}"
    async with get_store().session() as session:
        server2 = McpServerRepository().create(
            org_id=uuid.UUID(int=1), name=server2_name, transport="stdio",
            command="python other.py", url=None, headers=None, enabled=True,
        )
        await ToolDefinitionRepository().create(
            org_id=uuid.UUID(int=1), name=tool2, description="d", params_schema={},
            tool_type="execution", enabled=True, mcp_source=f"mcp:{server2.id}", mcp_tool_name=tool2,
        )
        await session.commit()
        # 全量同步（模拟启动）
        await ToolService().sync_registry_from_file()
    assert get(f"mc_{server_name}_{tool_a}") is not None  # 默认 org
    assert get(f"mc_{server2_name}_{tool2}") is not None  # 其他 org
    assert get(f"mc_{server2_name}_{tool2}").enabled is True
