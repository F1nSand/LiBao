"""T4 MCP 服务层测试（DB-backed）：注册建行+spec+默认关闭、重名 40904、遮蔽 40903、
连接失败 50201、enable 标志、注销禁用、列表 tool_count。

validate 用 monkeypatch 固定返回（不真连 server）。
"""
from __future__ import annotations

import socket
import uuid

import pytest

from app.api.schemas.tools import McpRegisterRequest
from app.core.errors import AppError
from app.core.security import hash_password
from app.services.mcp import McpService
from app.services.tool import ToolService
from app.storage.db import init_db
from app.storage.models import McpServer, Org, User
from app.storage.repositories.mcp_server import McpServerRepository
from app.tools.builtin import register_builtin_tools
from app.tools.mcp_client import McpConnectError, McpToolInfo
from app.tools.registry import all_tools, get, get_by_name, unregister


def _db_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 5432), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="Docker db 未运行")


FAKE_TOOLS = [
    McpToolInfo(name="echo", description="回声", input_schema={"type": "object", "properties": {}}),
    McpToolInfo(name="add", description="加法", input_schema={"type": "object", "properties": {}}),
]


@pytest.fixture
async def mcp_api_fixture(monkeypatch):
    register_builtin_tools()
    # 进程级 registry：async fixture 的 teardown 延迟执行（loop 关闭时），跨测试残留不可靠，
    # 改在 setup 幂等清理历史 MCP spec（顺序无关）
    for spec in [s for s in all_tools() if s.id.startswith("mc_")]:
        unregister(spec.id)
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-mcpapi-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"mcpapi_{uid}", password_hash=hash_password("x"), name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.commit()
    # validate 注入固定工具列表（注册验证路径不真连 server）
    monkeypatch.setattr("app.services.mcp.manager.validate", _fake_validate)
    yield sessionmaker, user
    await engine.dispose()


async def _fake_validate(cfg):
    # 按命令区分工具集：同测试内注册第二个 server 时避免工具名冲突（I7）
    if getattr(cfg, "command", None) == "python other.py":
        return [McpToolInfo(name="ping", description="P", input_schema={})]
    return list(FAKE_TOOLS)


def _req(url_or_command: str = "python demo.py", **kw) -> McpRegisterRequest:
    return McpRegisterRequest(url_or_command=url_or_command, **kw)


async def test_register_creates_server_and_tool_rows(mcp_api_fixture):
    sessionmaker, user = mcp_api_fixture
    async with sessionmaker() as session:
        res = await McpService().register(session, user, _req())
        assert res["server"]["name"] == "demo"  # 命令派生：python demo.py → demo
        assert res["server"]["transport"] == "stdio"
        assert res["server"]["enabled"] is True  # server 本身默认启用
        assert res["server"]["tool_count"] == 2
        assert [t["id"] for t in res["tools"]] == ["mc_demo_echo", "mc_demo_add"]
        server_id = res["server"]["id"]
        row = await session.get(McpServer, uuid.UUID(server_id))
        assert row.command == "python demo.py"
        # mcp_source 在工具行，不在 server 行
        from sqlalchemy import select

        from app.storage.models.tool_definition import ToolDefinition

        tools = list(
            (await session.execute(select(ToolDefinition).where(ToolDefinition.org_id == user.org_id))).scalars()
        )
        assert {t.name for t in tools} == {"echo", "add"}
        assert all(t.mcp_source == f"mcp:{server_id}" for t in tools)
        assert all(t.enabled is False for t in tools)


async def test_register_tools_default_disabled_and_spec_registered(mcp_api_fixture):
    sessionmaker, user = mcp_api_fixture
    async with sessionmaker() as session:
        res = await McpService().register(session, user, _req())
        for t in res["tools"]:
            assert t["enabled"] is False  # 默认关闭原则
        spec = get("mc_demo_echo")
        assert spec is not None
        assert spec.mcp_source == f"mcp:{res['server']['id']}"
        assert spec.handler is not None
        assert spec.enabled is False


async def test_register_http_transport(mcp_api_fixture):
    sessionmaker, user = mcp_api_fixture
    async with sessionmaker() as session:
        res = await McpService().register(session, user, _req("https://everything.mcp.local/mcp"))
        assert res["server"]["name"] == "everything"
        assert res["server"]["transport"] == "http"
        assert res["server"]["url_or_command"] == "https://everything.mcp.local/mcp"


async def test_register_name_conflict_40904(mcp_api_fixture):
    sessionmaker, user = mcp_api_fixture
    async with sessionmaker() as session:
        await McpService().register(session, user, _req())
        with pytest.raises(AppError) as exc:
            await McpService().register(session, user, _req("python demo.py"))  # 同名派生
        assert exc.value.code == 40904


async def test_register_tool_shadow_40903(mcp_api_fixture, monkeypatch):
    # I7：工具名与既有 registry 遮蔽 → 拒绝覆盖
    async def fake_validate_shadow(cfg):
        return [McpToolInfo(name="time_now", description="遮蔽", input_schema={})]

    monkeypatch.setattr("app.services.mcp.manager.validate", fake_validate_shadow)
    sessionmaker, user = mcp_api_fixture
    async with sessionmaker() as session:
        with pytest.raises(AppError) as exc:
            await McpService().register(session, user, _req("python shadow.py"))
        assert exc.value.code == 40903


async def test_register_connect_failure_50201(mcp_api_fixture, monkeypatch):
    async def fake_validate_fail(cfg):
        raise McpConnectError("server down")

    monkeypatch.setattr("app.services.mcp.manager.validate", fake_validate_fail)
    sessionmaker, user = mcp_api_fixture
    async with sessionmaker() as session:
        with pytest.raises(AppError) as exc:
            await McpService().register(session, user, _req())
        assert exc.value.code == 50201


async def test_register_enable_flag_controls_server_only(mcp_api_fixture):
    sessionmaker, user = mcp_api_fixture
    async with sessionmaker() as session:
        res = await McpService().register(session, user, _req(enable=False))
        assert res["server"]["enabled"] is False
        assert res["tools"][0]["enabled"] is False  # 工具仍默认关闭


async def test_list_servers_with_tool_count(mcp_api_fixture):
    sessionmaker, user = mcp_api_fixture
    async with sessionmaker() as session:
        await McpService().register(session, user, _req())
        await McpService().register(session, user, _req("python other.py"))
        servers = await McpService().list_servers(session, user.org_id)
        assert len(servers) == 2
        assert {s["name"] for s in servers} == {"demo", "other"}
        assert {s["tool_count"] for s in servers} == {2, 1}  # demo: echo/add；other: ping


async def test_unregister_disables_spec_and_hides_tools(mcp_api_fixture):
    sessionmaker, user = mcp_api_fixture
    async with sessionmaker() as session:
        res = await McpService().register(session, user, _req())
        server_id = res["server"]["id"]
        # 启用一个工具 → 注销后必须禁用
        await ToolService().set_enabled(session, user, "mc_demo_echo", True)
        assert get("mc_demo_echo").enabled is True

        await McpService().unregister(session, user, server_id)
        row = await McpServerRepository(session).get_by_id_org(user.org_id, uuid.UUID(server_id))
        assert row is None  # 软删后不再可见
        assert get("mc_demo_echo").enabled is False  # spec 禁用
        with pytest.raises(AppError) as exc:
            await ToolService().get_in_org(session, user.org_id, "mc_demo_echo")
        assert exc.value.code == 40405  # 工具行软删


async def test_unregister_missing_server_40406(mcp_api_fixture):
    sessionmaker, user = mcp_api_fixture
    async with sessionmaker() as session:
        with pytest.raises(AppError) as exc:
            await McpService().unregister(session, user, str(uuid.uuid4()))
        assert exc.value.code == 40406
