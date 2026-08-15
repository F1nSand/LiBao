"""MCP 源服务（docs 01 §7.2 / docs 03 §5.5）。

验证即注册：连接 → list_tools 成功才落库（失败 50201）；工具与内置工具同生命周期
（tool_definition 行 + registry spec，默认关闭、agent 勾选、confirm/幂等/超时全复用）。
同名遮蔽拒绝（I7）：工具名与既有 registry / 同 org 工具行冲突 → 40903。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.tools import McpRegisterRequest
from app.core.errors import (
    ERR_MCP_CONNECT,
    ERR_MCP_NAME_CONFLICT,
    ERR_MCP_SERVER_NOT_FOUND,
    ERR_TOOL_NAME_CONFLICT,
    AppError,
)
from app.services.serializers import serialize_mcp_server, serialize_tool_definition
from app.storage.models.mcp_server import McpServer
from app.storage.models.tool_definition import ToolDefinition
from app.storage.models.user import User
from app.storage.repositories.mcp_server import McpServerRepository
from app.storage.repositories.tool_definition import ToolDefinitionRepository
from app.tools.mcp_client import (
    McpConnConfig,
    McpConnectError,
    derive_server_name,
    parse_transport,
    slugify,
)
from app.tools.mcp_manager import manager
from app.tools.registry import ToolSpec, ToolType, get_by_name, register, unregister
from app.tools.sandbox import SandboxLevel


def conn_config_from_server(server: McpServer) -> McpConnConfig:
    """DB 行 → 运行时连接配置（启动重建/执行路径唯一映射点）。"""
    return McpConnConfig(
        transport=server.transport, command=server.command, url=server.url, headers=server.headers
    )


def mcp_spec_id(server_name: str, tool_name: str) -> str:
    """MCP spec id 派生（registry 键 + API 序列化 id 单一来源）。"""
    return f"mc_{slugify(server_name)}_{slugify(tool_name)}"


def _make_mcp_handler(server_id: str, cfg: McpConnConfig, tool_name: str):
    """MCP 工具 handler：经 manager 惰性连接执行；失败（含熔断）抛异常 → executor 错误路径。"""

    async def handler(**kw: Any) -> str:
        ok, text = await manager.call(server_id, cfg, tool_name, kw)
        if not ok:
            raise RuntimeError(text)  # 失败信息保留在 executor 的 error 文本
        return text

    return handler


def build_mcp_spec(server: McpServer, row: ToolDefinition, cfg: McpConnConfig) -> ToolSpec:
    """从 DB 行重建 MCP spec（register 与启动同步 T5 共用）：handler 惰性绑定，raw 名从 mcp_tool_name 取。"""
    return ToolSpec(
        id=mcp_spec_id(server.name, row.name),
        name=row.name,
        description=row.description,
        params_schema=row.params_schema,
        enabled=False,  # 同步后由调用方 set_enabled 跟随 DB
        sandbox=SandboxLevel.NONE,
        tool_type=ToolType.EXECUTION,
        mcp_source=row.mcp_source,
        timeout_ms=row.timeout_ms,
        handler=_make_mcp_handler(str(server.id), cfg, row.mcp_tool_name or row.name),
    )


class McpService:
    async def register(self, db: AsyncSession, user: User, req: McpRegisterRequest) -> dict[str, Any]:
        kind, payload = parse_transport(req.url_or_command)
        cfg = McpConnConfig(transport=kind, **payload, headers=req.headers)
        try:
            tools = await manager.validate(cfg)
        except McpConnectError as exc:
            raise AppError(ERR_MCP_CONNECT, f"MCP 连接失败: {exc}") from exc

        server_repo = McpServerRepository(db)
        name = (req.name or derive_server_name(req.url_or_command)).strip()
        if not name:
            raise AppError(ERR_MCP_CONNECT, "无法派生 MCP 源名称，请显式提供 name")
        if await server_repo.get_by_org_name(user.org_id, name):
            raise AppError(ERR_MCP_NAME_CONFLICT, f"MCP 源 {name} 已存在")

        # 第一遍：全量校验工具名（无副作用，冲突整体拒绝不产生半注册）。
        # I1：源内 slug 撞名（"HTTP GET" vs "http-get"）也在此拒绝，防第二遍 register 抛 ValueError。
        # I4：查全 org（registry 全局化后任何 org 同名行都会绑定到 spec）；批量查重（一条 IN 查询）。
        tool_repo = ToolDefinitionRepository(db)
        planned: list[tuple[Any, str]] = []
        seen_slugs: set[str] = set()
        for t in tools:
            tool_name = slugify(t.name)
            if not tool_name:
                continue
            if tool_name in seen_slugs:
                raise AppError(ERR_TOOL_NAME_CONFLICT, f"工具名 {tool_name} 在源内重复（slug 冲突）")
            seen_slugs.add(tool_name)
            if get_by_name(tool_name) is not None:
                raise AppError(ERR_TOOL_NAME_CONFLICT, f"工具名 {tool_name} 已被占用（I7 遮蔽拒绝）")
            planned.append((t, tool_name))
        if seen_slugs:
            existing = await tool_repo.names_exist_any_org(list(seen_slugs))
            if existing:
                raise AppError(
                    ERR_TOOL_NAME_CONFLICT, f"工具名 {'、'.join(sorted(existing))} 已被占用（I7 遮蔽拒绝）"
                )

        server = server_repo.create(
            org_id=user.org_id,
            name=name,
            transport=kind,
            command=payload.get("command"),
            url=payload.get("url"),
            headers=req.headers,
            enabled=req.enable if req.enable is not None else True,
        )
        await db.flush()

        # 第二遍：建行 + 注册 spec（此时不再抛业务错，无部分写入）；spec 构造复用 build_mcp_spec
        tool_rows: list[ToolDefinition] = []
        for t, tool_name in planned:
            row = await tool_repo.create(
                org_id=user.org_id,
                name=tool_name,
                description=t.description or "(MCP 工具)",
                params_schema=t.input_schema,
                tool_type="execution",
                enabled=False,  # 默认关闭原则（约束优先）
                mcp_source=f"mcp:{server.id}",
                mcp_tool_name=t.name,  # 原始工具名（重启重建 spec 时透传 call_tool）
            )
            register(build_mcp_spec(server, row, cfg))
            tool_rows.append(row)
        await db.commit()
        await db.refresh(server)
        return {
            "server": serialize_mcp_server(server, len(tool_rows)),
            "tools": [serialize_tool_definition(r) for r in tool_rows],
        }

    async def list_servers(self, db: AsyncSession, org_id: uuid.UUID) -> list[dict[str, Any]]:
        repo = McpServerRepository(db)
        rows = await repo.list_for_org(org_id)
        return [serialize_mcp_server(s, await repo.count_tools(org_id, f"mcp:{s.id}")) for s in rows]

    async def unregister(self, db: AsyncSession, user: User, server_id: str) -> None:
        try:
            server = await McpServerRepository(db).get_by_id_org(user.org_id, uuid.UUID(server_id))
        except ValueError:
            server = None
        if server is None:
            raise AppError(ERR_MCP_SERVER_NOT_FOUND, "MCP 源不存在")
        mcp_source = f"mcp:{server.id}"
        stmt = select(ToolDefinition).where(
            ToolDefinition.org_id == user.org_id,
            ToolDefinition.mcp_source == mcp_source,
            ToolDefinition.deleted_at.is_(None),
        )
        tool_rows = list((await db.execute(stmt)).scalars())
        server_repo = McpServerRepository(db)
        tool_repo = ToolDefinitionRepository(db)
        await server_repo.soft_delete(server)
        # 软删行 + 摘除 registry spec（I3：不残留 → 同进程重注册不被假 40903 挡）
        for row in tool_rows:
            await tool_repo.soft_delete(row)
            spec = get_by_name(row.name)
            if spec is not None:
                unregister(spec.id)
        await db.commit()
        await manager.close_connection(str(server.id))
