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
from app.tools.registry import get_by_name, patch_spec, set_enabled


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
        row = await ToolDefinitionRepository(db).get_by_org_name(org_id, resolve_name(tool_id))
        if row is None:
            raise AppError(ERR_TOOL_NOT_FOUND, "工具不存在或无权访问")
        return row

    async def create(self, db: AsyncSession, user: User, req: Any) -> ToolDefinition:
        repo = ToolDefinitionRepository(db)
        if await repo.name_exists(user.org_id, req.name):
            raise AppError(ERR_TOOL_NAME_CONFLICT, "同组织下已存在同名工具")
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

    async def sync_registry_from_db(self, db: AsyncSession) -> None:
        """启动同步（F7）：DB tool_definition.enabled 为事实源 → registry spec 跟随。

        使「停用的内置工具重启后不复活」（约束优先原则）。同名多 org 行时最后一行生效（M2 单 org 场景）。
        """
        rows = await ToolDefinitionRepository(db).list_for_org_all()
        for row in rows:
            spec = get_by_name(row.name)
            if spec is not None:
                set_enabled(spec.id, row.enabled)

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
