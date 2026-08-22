"""记忆数据访问（docs 04 §3.8）。卡片软删过滤；版本 append-only（JSONL 分文件）。

文件化：.agent/memory_cards.json（卡片 FileTable）+ .agent/memory/default/cards/<card_id>.versions.jsonl。
recent_messages_for_maintenance 走会话 JSONL 扫描。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.storage.file.store import get_store
from app.storage.models.memory import LongTermMemory, LongTermMemoryVersion
from app.storage.models.message import Message


class MemoryRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.store = get_store()
        self.table = self.store.table("memory_cards")

    def _versions_path(self, card_id: uuid.UUID) -> str:
        return f"memory/default/cards/{card_id}.versions.jsonl"

    # ---- maintenance 原料（改读 messages，docs 04 §3.2 message-as-log）----

    async def recent_messages_for_maintenance(self, user_id: uuid.UUID, limit: int) -> list[Message]:
        """maintenance 原料：该用户最近 user+assistant 消息（conversations.json 过滤归属 +
        排除软删会话/软删消息）。与旧 recent_traces 同语义：最近 limit 条按时间升序。"""
        convs = await self.store.table("conversations").list(
            filter_fn=lambda c: c.user_id == user_id and c.deleted_at is None
        )
        conv_ids = {str(c.id) for c in convs}
        all_msgs: list[Message] = []
        sessions_dir = self.store.root / "sessions"
        if sessions_dir.is_dir():
            for path in sessions_dir.glob("*.jsonl"):
                if path.stem not in conv_ids:
                    continue
                records = await self.store.jsonl_list(f"sessions/{path.name}")
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
        self.table.register(card)
        await self.store.jsonl_append(
            self._versions_path(card.id),
            LongTermMemoryVersion(memory_id=card.id, version=1, content=content, importance=importance).to_dict(),
        )
        return card

    async def add_version(self, card: LongTermMemory, content: dict, importance: float) -> None:
        await self.store.jsonl_append(
            self._versions_path(card.id),
            LongTermMemoryVersion(
                memory_id=card.id, version=card.current_version + 1, content=content, importance=importance
            ).to_dict(),
        )
        card.current_version += 1
        card.content = content
        card.importance = importance

    async def get_card(self, user_id: uuid.UUID, card_id: uuid.UUID) -> LongTermMemory | None:
        row = await self.table.get(card_id)
        if row is None or row.deleted_at is not None or row.user_id != user_id:
            return None
        return row

    async def list_cards(
        self, user_id: uuid.UUID, *, limit: int = 100, workspace_id: uuid.UUID | None = None
    ) -> list[LongTermMemory]:
        # M7-B 工作区记忆隔离：普通对话只取个人记忆（workspace_id 空）；工作区对话取（工作区 ∪ 个人）
        rows = await self.table.list(
            filter_fn=lambda c: (
                c.user_id == user_id
                and c.deleted_at is None
                and (c.workspace_id is None if workspace_id is None else c.workspace_id in (workspace_id, None))
            ),
            sort_key=lambda c: (c.importance, c.created_at),
            desc=True,
            limit=limit,
        )
        return rows

    async def soft_delete(self, card: LongTermMemory) -> None:
        card.deleted_at = datetime.now(UTC)

    async def list_versions(self, card_id: uuid.UUID) -> list[LongTermMemoryVersion]:
        records = await self.store.jsonl_list(self._versions_path(card_id))
        rows = [LongTermMemoryVersion.from_dict(r) for r in records]
        rows.sort(key=lambda v: v.version)
        return rows
