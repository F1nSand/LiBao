"""工具定义数据访问（docs 04 §3.5）。文件是工具元数据事实源；软删过滤。
文件化：.agent/tool_definitions.json。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.storage.file.store import get_store
from app.storage.models.tool_definition import ToolDefinition


class ToolDefinitionRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.table = get_store().table("tool_definitions")

    async def get_by_id(self, tool_id: uuid.UUID) -> ToolDefinition | None:
        row = await self.table.get(tool_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    async def get_by_org_name(self, org_id: uuid.UUID, name: str) -> ToolDefinition | None:
        rows = await self.table.list(
            filter_fn=lambda t: t.name == name and t.deleted_at is None, limit=1
        )
        return rows[0] if rows else None

    async def name_exists(self, org_id: uuid.UUID, name: str) -> bool:
        return await self.get_by_org_name(org_id, name) is not None

    async def name_exists_any_org(self, name: str) -> bool:
        """全量查重（M2.5 I4）：同名行绑定同名 spec，注册与建行对称查重。"""
        rows = await self.table.list(filter_fn=lambda t: t.name == name and t.deleted_at is None, limit=1)
        return len(rows) > 0

    async def names_exist_any_org(self, names: list[str]) -> list[str]:
        """批量全量查重（register 第一遍一条查询）。"""
        rows = await self.table.list(filter_fn=lambda t: t.name in names and t.deleted_at is None)
        return sorted({t.name for t in rows})

    async def list_for_org(
        self,
        org_id: uuid.UUID,
        *,
        enabled: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ToolDefinition]:
        return await self.table.list(
            filter_fn=lambda t: t.deleted_at is None and (enabled is None or t.enabled == enabled),
            sort_key=lambda t: t.created_at,
            desc=True,
            limit=limit,
            offset=offset,
        )

    async def count_for_org(self, org_id: uuid.UUID, *, enabled: bool | None = None) -> int:
        return await self.table.count(
            filter_fn=lambda t: t.deleted_at is None and (enabled is None or t.enabled == enabled)
        )

    async def list_for_org_all(self) -> list[ToolDefinition]:
        """全量非软删工具（启动同步 文件→registry 用）。"""
        return await self.table.list(filter_fn=lambda t: t.deleted_at is None)

    async def list_enabled_names(self, org_id: uuid.UUID) -> list[str]:
        """已启用的工具名（单通用 Agent 有效工具集：seed 精选 ∪ 已启用）。"""
        rows = await self.table.list(
            filter_fn=lambda t: t.enabled and t.deleted_at is None, sort_key=lambda t: t.name
        )
        return [t.name for t in rows]

    async def search(self, org_id: uuid.UUID, q: str, *, limit: int = 20) -> list[ToolDefinition]:
        """工具发现（REST 版 G3）：name/description 子串匹配。"""
        pattern = q.lower()
        rows = await self.table.list(
            filter_fn=lambda t: (
                t.deleted_at is None
                and (pattern in t.name.lower() or pattern in t.description.lower())
            ),
            sort_key=lambda t: t.created_at,
            desc=True,
            limit=limit,
        )
        return rows

    async def create(
        self,
        *,
        org_id: uuid.UUID,
        name: str,
        description: str,
        params_schema: dict[str, Any],
        tool_type: str,
        enabled: bool = False,
        require_confirm: bool = False,
        idempotent: bool = False,
        sandbox: str = "none",
        allowlist: list[str] | None = None,
        timeout_ms: int = 30000,
        max_concurrency: int = 1,
        mcp_source: str | None = None,
        mcp_tool_name: str | None = None,
    ) -> ToolDefinition:
        tool = ToolDefinition(
            org_id=org_id,
            name=name,
            description=description,
            params_schema=params_schema,
            tool_type=tool_type,
            enabled=enabled,
            require_confirm=require_confirm,
            idempotent=idempotent,
            sandbox=sandbox,
            allowlist=allowlist,
            timeout_ms=timeout_ms,
            max_concurrency=max_concurrency,
            mcp_source=mcp_source,
            mcp_tool_name=mcp_tool_name,
            version=1,
        )
        self.table.register(tool)
        return tool

    async def soft_delete(self, tool: ToolDefinition) -> None:
        tool.deleted_at = datetime.now(UTC)
