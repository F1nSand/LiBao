"""工具领域服务（docs 01 §7.1 / docs 03 §5.5）。

DB tool_definition 是元数据事实源，registry 是可执行实现宿主，按 name 绑定；
API id = registry spec.id（内置）或 "tl_" + name（无 spec 的 DB 工具）。
PATCH/DELETE 经 registry.set_enabled 同步启用态（默认关闭原则实时生效）。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_TOOL_NAME_CONFLICT, ERR_TOOL_NOT_FOUND, AppError
from app.services.serializers import serialize_tool_definition
from app.storage.models.tool_definition import ToolDefinition
from app.storage.models.user import User
from app.storage.repositories.tool_definition import ToolDefinitionRepository
from app.tools import executor
from app.tools.mcp_client import slugify
from app.tools.registry import get, get_by_name, patch_spec, register, set_enabled


def resolve_name(tool_id: str) -> str:
    """API id → DB name（registry 约定 tl_ 前缀；无前缀则按 id 直查兜底）。"""
    return tool_id.removeprefix("tl_")


class ToolService:
    async def list_for_org(
        self, db: AsyncSession, org_id: uuid.UUID, page: int, page_size: int, enabled: bool | None = None
    ) -> dict[str, Any]:
        repo = ToolDefinitionRepository(db)
        items = await repo.list_for_org(org_id, enabled=enabled, limit=page_size, offset=(page - 1) * page_size)
        total = await repo.count_for_org(org_id, enabled=enabled)
        from app.api.schemas.common import paged

        return paged([serialize_tool_definition(t) for t in items], total, page, page_size)

    async def get_in_org(self, db: AsyncSession, org_id: uuid.UUID, tool_id: str) -> ToolDefinition:
        # spec.id（内置 tl_* / MCP mc_*）优先解析为 spec.name；无 spec 的 DB 工具走 tl_ 前缀
        spec = get(tool_id)
        name = spec.name if spec is not None else resolve_name(tool_id)
        row = await ToolDefinitionRepository(db).get_by_org_name(org_id, name)
        if row is None:
            raise AppError(ERR_TOOL_NOT_FOUND, "工具不存在或无权访问")
        return row

    async def create(self, db: AsyncSession, user: User, req: Any) -> ToolDefinition:
        repo = ToolDefinitionRepository(db)
        # I4：org 内查重 + 全局 registry 查重（registry 全局化：同名 spec 会让本行绑定到他人工具）。
        # tl_* 内置 spec 是平台拥有的（M2 既定模式：DB 行绑定内置实现，如 time_now），不挡。
        if await repo.name_exists(user.org_id, req.name):
            raise AppError(ERR_TOOL_NAME_CONFLICT, "同组织下已存在同名工具")
        if (spec := get_by_name(req.name)) is not None and not spec.id.startswith("tl_"):
            raise AppError(ERR_TOOL_NAME_CONFLICT, f"工具名 {req.name} 已被注册工具占用（I7 遮蔽拒绝）")
        row = await repo.create(
            org_id=user.org_id,
            name=req.name,
            description=req.description or "",
            params_schema=req.params_schema or {"type": "object", "properties": {}, "required": []},
            tool_type=req.tool_type,
            enabled=False,  # 默认关闭原则（约束优先）
            require_confirm=req.require_confirm,
            idempotent=req.idempotent,
            sandbox=req.sandbox or "none",
            timeout_ms=req.timeout_ms or 30000,
            max_concurrency=req.max_concurrency or 1,
        )
        await db.commit()
        await db.refresh(row)
        return row

    async def update(self, db: AsyncSession, user: User, tool_id: str, req: Any) -> ToolDefinition:
        repo = ToolDefinitionRepository(db)
        row = await self.get_in_org(db, user.org_id, tool_id)
        if req.name is not None and req.name != row.name:
            if await repo.name_exists(user.org_id, req.name):
                raise AppError(ERR_TOOL_NAME_CONFLICT, "同组织下已存在同名工具")
            row.name = req.name
        for field, value in (
            ("description", req.description),
            ("params_schema", req.params_schema),
            ("tool_type", req.tool_type),
            ("require_confirm", req.require_confirm),
            ("idempotent", req.idempotent),
            ("sandbox", req.sandbox),
            ("timeout_ms", req.timeout_ms),
            ("max_concurrency", req.max_concurrency),
        ):
            if value is not None:
                setattr(row, field, value)
        await db.commit()
        await db.refresh(row)
        # 同步桥：运行时字段同步到 registry spec（require_confirm 等执行即刻生效）
        spec = get_by_name(row.name)
        if spec is not None:
            patch_spec(
                spec.id,
                require_confirm=row.require_confirm,
                idempotent=row.idempotent,
                sandbox=row.sandbox,
                timeout_ms=row.timeout_ms,
                max_concurrency=row.max_concurrency,
            )
        return row

    async def set_enabled(self, db: AsyncSession, user: User, tool_id: str, enabled: bool) -> ToolDefinition:
        row = await self.get_in_org(db, user.org_id, tool_id)
        row.enabled = enabled
        await db.commit()
        await db.refresh(row)
        # 同步桥：同名 registry spec 实时翻转（LLM ACI 与执行守卫立即生效）
        spec = get_by_name(row.name)
        if spec is not None:
            set_enabled(spec.id, enabled)
        return row

    async def soft_delete(self, db: AsyncSession, user: User, tool_id: str) -> None:
        row = await self.get_in_org(db, user.org_id, tool_id)
        await ToolDefinitionRepository(db).soft_delete(row)
        await db.commit()
        # 同步桥：内置工具删除即停用
        spec = get_by_name(row.name)
        if spec is not None:
            set_enabled(spec.id, False)

    async def sync_registry_from_db(self, db: AsyncSession, org_id: uuid.UUID | None = None) -> None:
        """启动同步（F7 + I5）：DB tool_definition.enabled 为事实源 → registry spec 跟随。

        - org_id 指定（默认组织）：已有 spec 的行 set_enabled 跟随（F7 原语义，防测试
          org 的 enabled=false 行把内置工具打成禁用）。
        - org_id=None（全量启动）：只做 MCP 行重建（I5：其他 org 的 MCP 工具重启后
          不能失效），不翻转已有 spec 的 enabled（防跨 org 污染）。
        MCP 行（mcp_source 非空）：registry 无同名 spec → 从 mcp_servers 重建（惰性 handler）；
        源已软删/停用 → 工具 spec 强制禁用。
        """
        repo = ToolDefinitionRepository(db)
        rows = await repo.list_for_org(org_id, limit=10000) if org_id else await repo.list_for_org_all()
        for row in rows:
            spec = get_by_name(row.name)
            if spec is not None:
                if org_id is not None:
                    set_enabled(spec.id, row.enabled)
            elif row.mcp_source:
                await self._sync_mcp_spec(db, row)

    async def _sync_mcp_spec(self, db: AsyncSession, row: ToolDefinition) -> None:
        """MCP 行重建：读 mcp_servers 配置 → build_mcp_spec 注册 → enabled 跟随 DB 与源状态。"""
        from app.services.mcp import build_mcp_spec
        from app.storage.repositories.mcp_server import McpServerRepository

        try:
            server_id = uuid.UUID(row.mcp_source.removeprefix("mcp:"))
        except ValueError:
            return  # M2：脏 mcp_source 行跳过，不击穿启动
        server = await McpServerRepository(db).get_by_id_including_deleted(server_id)
        if server is None:
            return  # 源行彻底缺失：无法重建（spec 缺席 = 不可见）
        usable = row.enabled and server.enabled and server.deleted_at is None
        spec_id = f"mc_{slugify(server.name)}_{slugify(row.name)}"
        if get_by_name(row.name) is not None:
            # 已注册（默认 org 同步或本趟前面已重建）：同步 enabled。
            # 多行同名时最后处理的行决定状态（生产被 I4 挡同名，此分支仅防脏数据）。
            set_enabled(spec_id, usable)
            return
        from app.tools.mcp_client import McpConnConfig

        cfg = McpConnConfig(
            transport=server.transport, command=server.command, url=server.url, headers=server.headers
        )
        register(build_mcp_spec(server, row, cfg))
        # 源软删/停用 → 工具强制禁用（可看到但不可执行）
        set_enabled(spec_id, usable)

    async def search(self, db: AsyncSession, org_id: uuid.UUID, q: str) -> list[dict[str, Any]]:
        rows = await ToolDefinitionRepository(db).search(org_id, q)
        # id 派生规则与 serialize_tool_definition 一致（单一来源）
        return [{k: serialize_tool_definition(t)[k] for k in ("id", "name", "description", "enabled")} for t in rows]

    async def test(self, db: AsyncSession, org_id: uuid.UUID, tool_id: str, params: dict[str, Any]) -> dict[str, Any]:
        row = await self.get_in_org(db, org_id, tool_id)
        spec = get_by_name(row.name)
        if spec is None:
            # 无 handler 的 DB 工具：确定性 echo（对齐 mock 语义），测试动作不 gate enabled
            return {"ok": True, "output": {"echo": params}, "duration_ms": 0}
        result = await executor.execute(spec, params)
        return {
            "ok": result.ok,
            "output": result.output,
            "duration_ms": result.duration_ms,
            "error": result.error,
        }
