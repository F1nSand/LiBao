"""记忆领域服务（docs 01 §8 / docs 03 §5.7）。

三层记忆之①轨迹（append-only，maintenance 原料）与②长期记忆（版本化只增：改写 = 新版本行）。
maintenance（LLM 整理）：读卡片+轨迹 → LLM 输出整理计划 → 单事务应用（只增原则）。
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ERR_LLM_FAILURE, ERR_MEMORY_NOT_FOUND, AppError
from app.core.llm import LLMService
from app.services.serializers import serialize_longterm_version, serialize_memory_trace
from app.storage.models.memory import LongTermMemory
from app.storage.repositories.memory import MemoryRepository

_MAINTENANCE_PROMPT = """你是记忆整理器。基于用户的长期记忆卡片与最近的对话轨迹，输出整理计划。
规则：
- importance 0-1（0=不重要，1=极重要）
- 原子事实优先，合并重复卡片
- json_card 存结构化数据，note 存 {"text": 字符串}
- 无意义/过时卡片放入 delete
只输出 JSON，结构：
{"keep": [卡片id], "update": [{"id": 卡片id, "content": {...}, "importance": 0-1}],
 "create": [{"content": {...}, "importance": 0-1, "card_type": "note|json_card"}], "delete": [卡片id]}"""


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


def _content_to_text(content: Any) -> str:
    """LLM content 规范化：str 直用；blocks 列表跳过 thinking 块（推理链），
    保留 text 块与裸字符串块（DeepSeek v4-flash 会把最终输出放在末位裸 str 块）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") != "thinking":
                parts.append(b.get("text", ""))
        return "".join(parts)
    return str(content)


def _extract_json(text: Any) -> dict:
    """LLM 输出 → dict。剥 ```json 围栏，取首个 { 到末个 }（DeepSeek 推理模型会包 markdown）。"""
    stripped = _content_to_text(text).strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(stripped[start : end + 1])


async def run_maintenance(db: AsyncSession, user_id: uuid.UUID, model: Any = None) -> dict[str, Any]:
    """LLM 整理（OA6）：读卡片+轨迹 → 计划 → 单事务应用（create/update=只增版本/delete=软删）。

    model 可注入（测试 FakeChatModel）；LLM 失败/解析失败 → 60001 retryable。
    """
    repo = MemoryRepository(db)
    cards = await repo.list_cards(user_id, limit=200)
    traces = await repo.recent_traces(user_id, get_settings().memory_trace_limit)
    cards_text = "\n".join(
        f"- [{c.id}] ({c.card_type}, importance={c.importance:.2f}) {c.title or ''}: "
        f"{json.dumps(c.content, ensure_ascii=False)}"
        for c in cards
    )
    traces_text = "\n".join(f"- [{t.role}] {t.content[:200]}" for t in traces)
    messages = [
        HumanMessage(
            content=f"{_MAINTENANCE_PROMPT}\n\n当前卡片:\n{cards_text or '(无)'}\n\n最近轨迹:\n{traces_text or '(无)'}"
        )
    ]
    try:
        if model is None:
            model = LLMService.build_model()
        response = await model.ainvoke(messages)
        plan = _extract_json(getattr(response, "content", "") or "")
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001  LLM 调用/解析失败 → 业务错误可重试
        raise AppError(ERR_LLM_FAILURE, f"记忆整理失败: {exc}", retryable=True) from exc
    if not isinstance(plan, dict):
        raise AppError(ERR_LLM_FAILURE, "记忆整理失败: 输出结构非法", retryable=True)

    created = updated = deleted = 0
    # keep：显式保留（不操作）
    # update：只增新版本
    for item in plan.get("update", []) or []:
        card = await repo.get_card(user_id, uuid.UUID(str(item["id"])))
        if card is None:
            continue
        importance = float(item.get("importance", card.importance))
        await repo.add_version(card, item.get("content") or card.content, max(0.0, min(1.0, importance)))
        updated += 1
    # create：新卡片（source=maintenance）
    for item in plan.get("create", []) or []:
        importance = float(item.get("importance", 0.5))
        await repo.create_card(
            user_id=user_id,
            card_type=item.get("card_type", "note"),
            content=item.get("content") or {},
            importance=max(0.0, min(1.0, importance)),
            source="maintenance",
        )
        created += 1
    # delete：软删
    for card_id in plan.get("delete", []) or []:
        card = await repo.get_card(user_id, uuid.UUID(str(card_id)))
        if card is not None:
            await repo.soft_delete(card)
            deleted += 1
    await db.commit()
    return {
        "summary": f"整理完成：更新 {updated} 张、新建 {created} 张、删除 {deleted} 张",
        "cards_created": created,
        "cards_updated": updated,
    }
