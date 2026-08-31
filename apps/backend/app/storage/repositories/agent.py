"""Agent 配置数据访问（《02》数据模型 §3.4）。单通用 Agent 模型：一条 is_default=True 的通用 Agent。

文件化：.agent/agents.json（AgentConfig）+ .agent/agent_versions.json（AgentVersion 快照）。
"""

from __future__ import annotations

import uuid

from app.storage.file.store import get_store
from app.storage.models.agent import AgentConfig, AgentVersion


class AgentRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.table = get_store().table("agents")
        self.versions = get_store().table("agent_versions")

    async def get_by_id(self, agent_id: uuid.UUID) -> AgentConfig | None:
        row = await self.table.get(agent_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    async def get_previous_version(self, agent_id: uuid.UUID, current_version: int) -> AgentVersion | None:
        """取当前版本之前的最近一版快照（回滚目标）。version < current_version 降序取 1。"""
        rows = await self.versions.list(
            filter_fn=lambda v: v.agent_id == agent_id and v.version < current_version,
            sort_key=lambda v: v.version,
            desc=True,
            limit=1,
        )
        return rows[0] if rows else None

    async def get_default(self, org_id: uuid.UUID, *, for_update: bool = False) -> AgentConfig | None:
        """取默认通用 Agent（is_default=True 且 published 未软删）；
        回退：无 is_default 标记的旧数据 → 首个 published（存量兼容）。
        for_update 为双轨兼容参数（文件单进程无行锁需求）。"""
        rows = await self.table.list(
            filter_fn=lambda a: a.status == "published" and a.deleted_at is None,
            sort_key=lambda a: a.created_at,
            desc=True,
        )
        default = next((a for a in rows if a.is_default), None)
        return default or (rows[0] if rows else None)
