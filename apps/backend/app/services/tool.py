"""工具领域服务（《02》后端设计 §7.1 / 《02》接口契约 §5.5）。

DB tool_definition 是元数据事实源，registry 是可执行实现宿主，按 name 绑定；
API id = registry spec.id（内置）或 "tl_" + name（无 spec 的 DB 工具）。
PATCH/DELETE 经 registry.set_enabled 同步启用态（默认关闭原则实时生效）。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.errors import ERR_PARAM_MISSING, ERR_TOOL_NAME_CONFLICT, ERR_TOOL_NOT_FOUND, AppError
from app.services.serializers import serialize_tool_definition
from app.storage.file.store import get_store
from app.storage.models.tool_definition import ToolDefinition
from app.storage.models.user import User
from app.storage.repositories.tool_definition import ToolDefinitionRepository
from app.tools import executor
from app.tools.registry import get, get_by_name, patch_spec, register, set_enabled
from app.tools.sandbox import SandboxLevel


def resolve_name(tool_id: str) -> str:
    """API id → DB name（registry 约定 tl_ 前缀；无前缀则按 id 直查兜底）。"""
    return tool_id.removeprefix("tl_")


def _sandbox_level(value: SandboxLevel | str) -> SandboxLevel:
    """持久化字符串 → 运行时枚举，旧脏值不得进入 registry。"""
    try:
        return value if isinstance(value, SandboxLevel) else SandboxLevel(value)
    except ValueError as exc:
        raise AppError(ERR_PARAM_MISSING, f"不支持的沙盒级别: {value}") from exc


class ToolService:
    async def list_for_org(
        self, db: Any, org_id: uuid.UUID, page: int, page_size: int, enabled: bool | None = None
    ) -> dict[str, Any]:
        repo = ToolDefinitionRepository(db)
        items = await repo.list_for_org(org_id, enabled=enabled, limit=page_size, offset=(page - 1) * page_size)
        total = await repo.count_for_org(org_id, enabled=enabled)
        from app.api.schemas.common import paged

        return paged([serialize_tool_definition(t) for t in items], total, page, page_size)

    async def get_in_org(self, db: Any, org_id: uuid.UUID, tool_id: str) -> ToolDefinition:
        # spec.id（内置 tl_* / MCP mc_*）优先解析为 spec.name；无 spec 的 DB 工具走 tl_ 前缀
        spec = get(tool_id)
        name = spec.name if spec is not None else resolve_name(tool_id)
        row = await ToolDefinitionRepository(db).get_by_org_name(org_id, name)
        if row is None:
            raise AppError(ERR_TOOL_NOT_FOUND, "工具不存在或无权访问")
        return row

    async def create(self, db: Any, user: User, req: Any) -> ToolDefinition:
        repo = ToolDefinitionRepository(db)
        # I4：org 内查重 + 全局 registry 查重（registry 全局化：同名 spec 会让本行绑定到他人工具）。
        # tl_* 内置 spec 是平台拥有的（M2 既定模式：DB 行绑定内置实现，如 time_now），不挡。
        if await repo.name_exists(user.org_id, req.name):
            raise AppError(ERR_TOOL_NAME_CONFLICT, "同组织下已存在同名工具")
        if (spec := get_by_name(req.name)) is not None and not spec.builtin:
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
            sandbox=_sandbox_level(req.sandbox or SandboxLevel.NONE).value,
            timeout_ms=req.timeout_ms or 30000,
            max_concurrency=req.max_concurrency or 1,
        )
        await db.commit()
        await db.refresh(row)
        return row

    async def update(self, db: Any, user: User, tool_id: str, req: Any) -> ToolDefinition:
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
            ("timeout_ms", req.timeout_ms),
            ("max_concurrency", req.max_concurrency),
        ):
            if value is not None:
                setattr(row, field, value)
        if req.sandbox is not None:
            row.sandbox = _sandbox_level(req.sandbox).value
        await db.commit()
        await db.refresh(row)
        # 同步桥：运行时字段同步到 registry spec（require_confirm 等执行即刻生效）
        spec = get_by_name(row.name)
        if spec is not None:
            patch_spec(
                spec.id,
                require_confirm=row.require_confirm,
                idempotent=row.idempotent,
                sandbox=_sandbox_level(row.sandbox),
                timeout_ms=row.timeout_ms,
                max_concurrency=row.max_concurrency,
            )
        return row

    async def set_enabled(self, db: Any, user: User, tool_id: str, enabled: bool) -> ToolDefinition:
        row = await self.get_in_org(db, user.org_id, tool_id)
        row.enabled = enabled
        await db.commit()
        await db.refresh(row)
        # 同步桥：同名 registry spec 实时翻转（LLM ACI 与执行守卫立即生效）
        spec = get_by_name(row.name)
        if spec is not None:
            set_enabled(spec.id, enabled)
        return row

    async def soft_delete(self, db: Any, user: User, tool_id: str) -> None:
        row = await self.get_in_org(db, user.org_id, tool_id)
        await ToolDefinitionRepository(db).soft_delete(row)
        await db.commit()
        # 同步桥：内置工具删除即停用
        spec = get_by_name(row.name)
        if spec is not None:
            set_enabled(spec.id, False)

    async def sync_registry_from_file(self) -> None:
        """启动同步（本地单机化）：tool_definitions.json enabled 为事实源 → registry spec 跟随。

        已有 spec 的行 set_enabled 跟随；MCP 行（mcp_source 非空）：registry 无同名 spec →
        从 mcp_servers.json 重建（惰性 handler）；源已软删/停用 → 工具 spec 强制禁用。
        """
        repo = ToolDefinitionRepository()
        rows = await repo.list_for_org_all()
        servers_by_id = await self._load_mcp_servers(rows)
        for row in rows:
            spec = get_by_name(row.name)
            sandbox = _sandbox_level(row.sandbox)
            if spec is not None:
                patch_spec(spec.id, sandbox=sandbox)
                set_enabled(spec.id, row.enabled)
            elif row.mcp_source:
                self._sync_mcp_spec(row, servers_by_id)

    async def _load_mcp_servers(self, mcp_rows: list[ToolDefinition]) -> dict[uuid.UUID, Any]:
        """读 mcp_servers.json 全量（含软删，语义同 get_by_id_including_deleted），按 server_id 映射。"""

        rows = await get_store().table("mcp_servers").list()
        return {s.id: s for s in rows}

    def _sync_mcp_spec(self, row: ToolDefinition, servers_by_id: dict[uuid.UUID, Any]) -> None:
        """MCP 行重建：build_mcp_spec 注册 → enabled 跟随 DB 与源状态（server 已批量预取）。"""
        from app.services.mcp import build_mcp_spec, conn_config_from_server, mcp_spec_id

        try:
            server_id = uuid.UUID(row.mcp_source.removeprefix("mcp:"))
        except ValueError:
            return  # M2：脏 mcp_source 行跳过，不击穿启动
        server = servers_by_id.get(server_id)
        if server is None:
            return  # 源行彻底缺失：无法重建（spec 缺席 = 不可见）
        usable = row.enabled and server.enabled and server.deleted_at is None
        if get_by_name(row.name) is None:
            # 未注册（默认 org 同步或本趟前面已重建）：重建 spec
            register(build_mcp_spec(server, row, conn_config_from_server(server)))
        # 已注册或刚重建：同步 enabled（多行同名时最后处理的行决定状态；生产被 I4 挡同名，防脏数据）
        set_enabled(mcp_spec_id(server.name, row.name), usable)

    async def search(self, db: Any, org_id: uuid.UUID, q: str) -> list[dict[str, Any]]:
        rows = await ToolDefinitionRepository(db).search(org_id, q)
        # id 派生规则与 serialize_tool_definition 一致（单一来源）；排除 meta 工具（平台发现层不自发现）
        return [
            {k: serialize_tool_definition(t)[k] for k in ("id", "name", "description", "enabled")}
            for t in rows
            if (spec := get_by_name(t.name)) is None or not spec.meta
        ]

    async def enabled_tool_ids(self, db: Any, org_id: uuid.UUID) -> list[str]:
        """本组织已启用工具 → registry spec id（MCP/自定义启用即对通用助手开放，org 隔离）。"""
        names = await ToolDefinitionRepository(db).list_enabled_names(org_id)
        ids = []
        for n in names:
            spec = get_by_name(n)
            ids.append(spec.id if spec is not None else f"tl_{n}")
        return ids

    async def test(self, db: Any, org_id: uuid.UUID, tool_id: str, params: dict[str, Any]) -> dict[str, Any]:
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
