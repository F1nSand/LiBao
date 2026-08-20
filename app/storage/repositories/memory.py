"""记忆数据访问（docs 04 §3.8）。轨迹 append-only；卡片软删过滤；版本 UNIQUE(memory_id, version)。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.memory import LongTermMemory, LongTermMemoryVersion, MemoryTrace


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- 轨迹（append-only）----

    async def add_trace(
        self,
        *,
        user_id: uuid.UUID,
        role: str,
        content: str,
        trace_id: str | None = None,
        conversation_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
        meta: dict | None = None,
    ) -> MemoryTrace:
        row = MemoryTrace(
            user_id=user_id,
            role=role,
            content=content,
            trace_id=trace_id,
            conversation_id=conversation_id,
            message_id=message_id,
            meta=meta,
        )
        self.session.add(row)
        return row

    async def list_traces(
        self, user_id: uuid.UUID, *, limit: int, offset: int, conversation_id: uuid.UUID | None = None
    ) -> list[MemoryTrace]:
        stmt = select(MemoryTrace).where(MemoryTrace.user_id == user_id)
        if conversation_id is not None:
            stmt = stmt.where(MemoryTrace.conversation_id == conversation_id)
        stmt = stmt.order_by(MemoryTrace.created_at.asc()).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars())

    async def count_traces(self, user_id: uuid.UUID, conversation_id: uuid.UUID | None = None) -> int:
        stmt = select(func.count()).select_from(MemoryTrace).where(MemoryTrace.user_id == user_id)
        if conversation_id is not None:
            stmt = stmt.where(MemoryTrace.conversation_id == conversation_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def recent_traces(self, user_id: uuid.UUID, limit: int) -> list[MemoryTrace]:
        stmt = (
            select(MemoryTrace)
            .where(MemoryTrace.user_id == user_id)
            .order_by(MemoryTrace.created_at.desc())
            .limit(limit)
        )
        return list(reversed((await self.session.execute(stmt)).scalars().all()))

    # ---- 长期记忆卡片 ----

    async def create_card(
        self,
        *,
        user_id: uuid.UUID,
        card_type: str,
        content: dict,
        title: str | None = None,
        tags: list[str] | None = None,
        importance: float = 0.0,
        source: str = "manual",
        workspace_id: uuid.UUID | None = None,
    ) -> LongTermMemory:
        card = LongTermMemory(
            user_id=user_id,
            workspace_id=workspace_id,
            card_type=card_type,
            title=title,
            content=content,
            tags=tags,
            importance=importance,
            source=source,
            current_version=1,
        )
        self.session.add(card)
        await self.session.flush()
        self.session.add(
            LongTermMemoryVersion(
                memory_id=card.id, version=1, content=content, importance=importance
            )
        )
        return card

    async def add_version(self, card: LongTermMemory, content: dict, importance: float) -> None:
        self.session.add(
            LongTermMemoryVersion(
                memory_id=card.id, version=card.current_version + 1, content=content, importance=importance
            )
        )
        card.current_version += 1
        card.content = content
        card.importance = importance

    async def get_card(self, user_id: uuid.UUID, card_id: uuid.UUID) -> LongTermMemory | None:
        stmt = select(LongTermMemory).where(
            LongTermMemory.user_id == user_id,
            LongTermMemory.id == card_id,
            LongTermMemory.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_cards(
        self, user_id: uuid.UUID, *, limit: int = 100, workspace_id: uuid.UUID | None = None
    ) -> list[LongTermMemory]:
        stmt = select(LongTermMemory).where(
            LongTermMemory.user_id == user_id, LongTermMemory.deleted_at.is_(None)
        )
        # M7-B 工作区记忆隔离：普通对话只取个人记忆（workspace_id IS NULL）；
        # 工作区对话取（工作区记忆 ∪ 个人记忆）
        if workspace_id is None:
            stmt = stmt.where(LongTermMemory.workspace_id.is_(None))
        else:
            stmt = stmt.where(
                or_(LongTermMemory.workspace_id == workspace_id, LongTermMemory.workspace_id.is_(None))
            )
        stmt = stmt.order_by(LongTermMemory.importance.desc(), LongTermMemory.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars())

    async def soft_delete(self, card: LongTermMemory) -> None:
        card.deleted_at = datetime.now(UTC)
        self.session.add(card)

    async def list_versions(self, card_id: uuid.UUID) -> list[LongTermMemoryVersion]:
        stmt = (
            select(LongTermMemoryVersion)
            .where(LongTermMemoryVersion.memory_id == card_id)
            .order_by(LongTermMemoryVersion.version.asc())
        )
        return list((await self.session.execute(stmt)).scalars())
