"""记忆数据访问（docs 04 §3.8）。卡片软删过滤；版本 UNIQUE(memory_id, version)。
maintenance 原料改读 messages（memory_trace 已删，见迁移 0016）。
文件化：卡片/版本 P2 转换；recent_messages_for_maintenance 已改文件扫描。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.file.store import get_store
from app.storage.models.memory import LongTermMemory, LongTermMemoryVersion
from app.storage.models.message import Message


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- maintenance 原料（改读 messages，docs 04 §3.2 message-as-log）----

    async def recent_messages_for_maintenance(self, user_id: uuid.UUID, limit: int) -> list[Message]:
        """maintenance 原料：该用户最近 user+assistant 消息（join conversations 过滤 user_id +
        排除软删会话/软删消息）。与旧 recent_traces 同语义：最近 limit 条按时间升序。

        文件化：扫描全部会话 JSONL 归并（个人量级文件数少；conversations.json 过滤归属）。
        """
        store = get_store()
        convs = await store.table("conversations").list(
            filter_fn=lambda c: c.user_id == user_id and c.deleted_at is None
        )
        conv_ids = {str(c.id) for c in convs}
        all_msgs: list[Message] = []
        sessions_dir = store.root / "sessions"
        if sessions_dir.is_dir():
            for path in sessions_dir.glob("*.jsonl"):
                if path.stem not in conv_ids:
                    continue
                records = await store.jsonl_list(f"sessions/{path.name}")
                all_msgs.extend(
                    Message.from_dict(r)
                    for r in records
                    if r.get("role") in ("user", "assistant") and not r.get("deleted_at")
                )
        all_msgs.sort(key=lambda m: m.created_at, reverse=True)
        return list(reversed(all_msgs[:limit]))

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
