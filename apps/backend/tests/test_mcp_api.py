"""T4 MCP 服务层测试（文件存储）：注册建行+spec+默认关闭、重名 40904、遮蔽 40903、
连接失败 50201、enable 标志、注销禁用、列表 tool_count。

validate 用 monkeypatch 固定返回（不真连 server）。
本地单机化：user 用 ADMIN_USER（org 概念已折叠，查重全库全局）。
"""
from __future__ import annotations

import uuid

import pytest

from app.api.schemas.tools import CreateToolRequest, McpRegisterRequest
from app.core.errors import AppError
from app.services.mcp import McpService
from app.services.tool import ToolService
from app.storage.constants import ADMIN_USER
from app.storage.file.store import get_store
from app.storage.repositories.mcp_server import McpServerRepository
from app.storage.repositories.tool_definition import ToolDefinitionRepository
from app.tools.mcp_client import McpConnectError, McpToolInfo
from app.tools.registry import get, get_by_name


def _fake_tools(uid: str, second_server: bool = False) -> list[McpToolInfo]:
    """按 uid 生成工具名：name_exists_any_org 查全库，残留测试行的同名工具会误伤断言。"""
    if second_server:
        return [McpToolInfo(name=f"ping_{uid}", description="P", input_schema={})]
    return [
        McpToolInfo(name=f"echo_{uid}", description="回声", input_schema={"type": "object", "properties": {}}),
        McpToolInfo(name=f"add_{uid}", description="加法", input_schema={"type": "object", "properties": {}}),
    ]


@pytest.fixture
async def mcp_api_fixture(clean_mcp_specs, monkeypatch):
    uid = uuid.uuid4().hex[:8]
    tool_a, tool_b = f"echo_{uid}", f"add_{uid}"
    user = ADMIN_USER
    tools_a = _fake_tools(uid)

    async def _fake_validate(cfg):
        # 按命令区分工具集：同测试内注册第二个 server 时避免工具名冲突（I7）
        if getattr(cfg, "command", None) == "python other.py":
            return _fake_tools(uid, second_server=True)
        return list(tools_a)

    monkeypatch.setattr("app.services.mcp.manager.validate", _fake_validate)
    yield user, tool_a, tool_b


def _req(url_or_command: str = "python demo.py", **kw) -> McpRegisterRequest:
    return McpRegisterRequest(url_or_command=url_or_command, **kw)


async def test_register_creates_server_and_tool_rows(mcp_api_fixture):
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        res = await McpService().register(session, user, _req())
        assert res["server"]["name"] == "demo"  # 命令派生：python demo.py → demo
        assert res["server"]["transport"] == "stdio"
        assert res["server"]["enabled"] is True  # server 本身默认启用
        assert res["server"]["tool_count"] == 2
        assert [t["id"] for t in res["tools"]] == [f"mc_demo_{tool_a}", f"mc_demo_{tool_b}"]
        server_id = res["server"]["id"]
        row = await McpServerRepository().get_by_id_including_deleted(uuid.UUID(server_id))
        assert row.command == "python demo.py"
        # mcp_source 在工具行，不在 server 行
        tools = await ToolDefinitionRepository().list_for_org_all()
        assert {t.name for t in tools} == {tool_a, tool_b}
        assert all(t.mcp_source == f"mcp:{server_id}" for t in tools)
        assert all(t.enabled is False for t in tools)


async def test_register_tools_default_disabled_and_spec_registered(mcp_api_fixture):
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        res = await McpService().register(session, user, _req())
        for t in res["tools"]:
            assert t["enabled"] is False  # 默认关闭原则
        spec = get(f"mc_demo_{tool_a}")
        assert spec is not None
        assert spec.mcp_source == f"mcp:{res['server']['id']}"
        assert spec.handler is not None
        assert spec.enabled is False


async def test_register_http_transport(mcp_api_fixture):
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        res = await McpService().register(session, user, _req("https://everything.mcp.local/mcp"))
        assert res["server"]["name"] == "everything"
        assert res["server"]["transport"] == "http"
        assert res["server"]["url_or_command"] == "https://everything.mcp.local/mcp"


async def test_register_name_conflict_40904(mcp_api_fixture):
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        await McpService().register(session, user, _req())
        with pytest.raises(AppError) as exc:
            await McpService().register(session, user, _req("python demo.py"))  # 同名派生
        assert exc.value.code == 40904


async def test_register_tool_shadow_40903(mcp_api_fixture, monkeypatch):
    # I7：工具名与既有 registry 遮蔽 → 拒绝覆盖
    async def fake_validate_shadow(cfg):
        return [McpToolInfo(name="time_now", description="遮蔽", input_schema={})]

    monkeypatch.setattr("app.services.mcp.manager.validate", fake_validate_shadow)
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        with pytest.raises(AppError) as exc:
            await McpService().register(session, user, _req("python shadow.py"))
        assert exc.value.code == 40903


async def test_register_connect_failure_50201(mcp_api_fixture, monkeypatch):
    async def fake_validate_fail(cfg):
        raise McpConnectError("server down")

    monkeypatch.setattr("app.services.mcp.manager.validate", fake_validate_fail)
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        with pytest.raises(AppError) as exc:
            await McpService().register(session, user, _req())
        assert exc.value.code == 50201


async def test_register_enable_flag_controls_server_only(mcp_api_fixture):
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        res = await McpService().register(session, user, _req(enable=False))
        assert res["server"]["enabled"] is False
        assert res["tools"][0]["enabled"] is False  # 工具仍默认关闭


async def test_list_servers_with_tool_count(mcp_api_fixture):
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        await McpService().register(session, user, _req())
        await McpService().register(session, user, _req("python other.py"))
        servers = await McpService().list_servers(session, user.org_id)
        assert len(servers) == 2
        assert {s["name"] for s in servers} == {"demo", "other"}
        assert {s["tool_count"] for s in servers} == {2, 1}  # demo: echo/add；other: ping


async def test_unregister_removes_spec_and_hides_tools(mcp_api_fixture):
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        res = await McpService().register(session, user, _req())
        server_id = res["server"]["id"]
        await ToolService().set_enabled(session, user, f"mc_demo_{tool_a}", True)
        assert get(f"mc_demo_{tool_a}").enabled is True

        await McpService().unregister(session, user, server_id)
        row = await McpServerRepository().get_by_id_org(user.org_id, uuid.UUID(server_id))
        assert row is None  # 软删后不再可见
        assert get(f"mc_demo_{tool_a}") is None  # I3：spec 摘除（不残留）
        with pytest.raises(AppError) as exc:
            await ToolService().get_in_org(session, user.org_id, f"mc_demo_{tool_a}")
        assert exc.value.code == 40405  # 工具行软删


async def test_unregister_then_reregister_same_process(mcp_api_fixture):
    # I3：注销后同进程内重注册（注册错 URL 的补救路径）不再被残留 spec 假 40903 挡住
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        res1 = await McpService().register(session, user, _req("python bad.py"))
        await McpService().unregister(session, user, res1["server"]["id"])
        res2 = await McpService().register(session, user, _req("python bad.py"))  # 同名重注册
        assert res2["server"]["name"] == "bad"
        assert len(res2["tools"]) == 2


async def test_register_slug_collision_40903(mcp_api_fixture, monkeypatch):
    # I1：源内 slug 撞名（"HTTP GET" vs "http-get" → http_get）→ 40903，不产生半注册
    async def fake_validate_collision(cfg):
        return [
            McpToolInfo(name="HTTP GET", description="a", input_schema={}),
            McpToolInfo(name="http-get", description="b", input_schema={}),
        ]

    monkeypatch.setattr("app.services.mcp.manager.validate", fake_validate_collision)
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        with pytest.raises(AppError) as exc:
            await McpService().register(session, user, _req("python collide.py"))
        assert exc.value.code == 40903
        assert get_by_name("http_get") is None  # 无残留 spec


async def test_cross_org_custom_tool_blocked_by_mcp_spec(mcp_api_fixture):
    # I4：先注册 MCP 工具 echo → 建同名自定义工具 → 40903（查重全库全局）
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        await McpService().register(session, user, _req("python a.py"))
        with pytest.raises(AppError) as exc:
            await ToolService().create(session, user, CreateToolRequest(name=tool_a))
        assert exc.value.code == 40903


async def test_cross_org_mcp_register_blocked_by_other_org_row(mcp_api_fixture, monkeypatch):
    # I4：先建自定义工具 ping → 注册 MCP 工具 ping → 40903（查全库）
    async def fake_validate_ping(cfg):
        return [McpToolInfo(name="ping", description="P", input_schema={})]

    monkeypatch.setattr("app.services.mcp.manager.validate", fake_validate_ping)
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        await ToolService().create(session, user, CreateToolRequest(name="ping"))
        with pytest.raises(AppError) as exc:
            await McpService().register(session, user, _req("python a.py"))
        assert exc.value.code == 40903


async def test_unregister_missing_server_40406(mcp_api_fixture):
    user, tool_a, tool_b = mcp_api_fixture
    async with get_store().session() as session:
        with pytest.raises(AppError) as exc:
            await McpService().unregister(session, user, str(uuid.uuid4()))
        assert exc.value.code == 40406
