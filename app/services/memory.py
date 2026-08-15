"""记忆领域服务（docs 01 §8 / docs 03 §5.7）。

三层记忆之①轨迹（append-only，maintenance 原料）与②长期记忆（版本化只增：改写 = 新版本行）。
maintenance（LLM 整理）在 T4 实现。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_MEMORY_NOT_FOUND, AppError
from app.services.serializers import serialize_longterm_version, serialize_memory_trace
from app.storage.models.memory import LongTermMemory
from app.storage.repositories.memory import MemoryRepository


class MemoryService:
    # ---- 轨迹 ----

    async def record_trace(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        role: str,
        content: str,
        trace_id: str | None = None,
        conversation_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
        meta: dict | None = None,
    ) -> None:
        await MemoryRepository(db).add_trace(
            user_id=user_id,
            role=role,
            content=content[:1000],  # 轨迹截断（防膨胀）
            trace_id=trace_id,
            conversation_id=conversation_id,
            message_id=message_id,
            meta=meta,
        )

    async def list_traces(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        page: int,
        page_size: int,
        conversation_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        repo = MemoryRepository(db)
        items = await repo.list_traces(
            user_id, limit=page_size, offset=(page - 1) * page_size, conversation_id=conversation_id
        )
        total = await repo.count_traces(user_id, conversation_id=conversation_id)
        from app.api.schemas.common import paged

        return paged([serialize_memory_trace(t) for t in items], total, page, page_size)

    # ---- 长期记忆卡片 ----

    async def create_card(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        card_type: str,
        title: str | None,
        body: dict,
        tags: list[str] | None = None,
        importance: float = 0.0,
    ) -> LongTermMemory:
        card = await MemoryRepository(db).create_card(
            user_id=user_id,
            card_type=card_type,
            content=body,
            title=title,
            tags=tags,
            importance=max(0.0, min(1.0, importance)),
        )
        await db.commit()
        return card

    async def update_card(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        card_id: uuid.UUID,
        content: dict,
        importance: float | None = None,
    ) -> LongTermMemory:
        """改写 = 只增新版本（ADR-06），importance 可选更新。"""
        repo = MemoryRepository(db)
        card = await repo.get_card(user_id, card_id)
        if card is None:
            raise AppError(ERR_MEMORY_NOT_FOUND, "记忆卡片不存在")
        new_importance = importance if importance is not None else card.importance
        await repo.add_version(card, content, max(0.0, min(1.0, new_importance)))
        await db.commit()
        return card

    async def list_cards(self, db: AsyncSession, user_id: uuid.UUID) -> list[LongTermMemory]:
        return await MemoryRepository(db).list_cards(user_id)

    async def get_card(self, db: AsyncSession, user_id: uuid.UUID, card_id: uuid.UUID) -> LongTermMemory:
        card = await MemoryRepository(db).get_card(user_id, card_id)
        if card is None:
            raise AppError(ERR_MEMORY_NOT_FOUND, "记忆卡片不存在")
        return card

    async def soft_delete(self, db: AsyncSession, user_id: uuid.UUID, card_id: uuid.UUID) -> None:
        card = await self.get_card(db, user_id, card_id)
        await MemoryRepository(db).soft_delete(card)
        await db.commit()

    async def list_versions(self, db: AsyncSession, user_id: uuid.UUID, card_id: uuid.UUID) -> list[dict]:
        card = await self.get_card(db, user_id, card_id)
        return [serialize_longterm_version(v, card.title) for v in await MemoryRepository(db).list_versions(card.id)]
