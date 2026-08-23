"""记忆领域服务（docs 01 §8 / docs 03 §5.7）。

长期记忆（版本化只增：改写 = 新版本行）。maintenance（LLM 整理）：读卡片 + 最近 messages
（memory_trace 已删改读 messages，见迁移 0016）→ LLM 输出整理计划 → 单事务应用（只增原则）。
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from langchain_core.messages import HumanMessage

from app.core.config import get_settings
from app.core.errors import ERR_LLM_FAILURE, ERR_MEMORY_NOT_FOUND, AppError
from app.core.llm import LLMService
from app.core.messages import message_text  # 独立模块（防 stream_core 导入环）
from app.services.serializers import serialize_longterm_version
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
    # ---- 长期记忆卡片 ----

    async def create_card(
        self,
        db: Any,
        user_id: uuid.UUID,
        card_type: str,
        title: str | None,
        body: dict,
        tags: list[str] | None = None,
        importance: float = 0.0,
        workspace_id: uuid.UUID | None = None,
    ) -> LongTermMemory:
        card = await MemoryRepository(db).create_card(
            user_id=user_id,
            card_type=card_type,
            content=body,
            title=title,
            tags=tags,
            importance=_clamp_importance(importance),
            workspace_id=workspace_id,
        )
        await db.commit()
        return card

    async def update_card(
        self,
        db: Any,
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
        await repo.add_version(card, content, _clamp_importance(new_importance))
        await db.commit()
        return card

    async def list_cards(self, db: Any, user_id: uuid.UUID) -> list[LongTermMemory]:
        return await MemoryRepository(db).list_cards(user_id)

    async def get_card(self, db: Any, user_id: uuid.UUID, card_id: uuid.UUID) -> LongTermMemory:
        card = await MemoryRepository(db).get_card(user_id, card_id)
        if card is None:
            raise AppError(ERR_MEMORY_NOT_FOUND, "记忆卡片不存在")
        return card

    async def soft_delete(self, db: Any, user_id: uuid.UUID, card_id: uuid.UUID) -> None:
        card = await self.get_card(db, user_id, card_id)
        await MemoryRepository(db).soft_delete(card)
        await db.commit()

    async def list_versions(self, db: Any, user_id: uuid.UUID, card_id: uuid.UUID) -> list[dict]:
        card = await self.get_card(db, user_id, card_id)
        return [serialize_longterm_version(v, card.title) for v in await MemoryRepository(db).list_versions(card.id)]

    async def list_project_memory(self, workspace_root: str) -> list[dict[str, Any]]:
        """工作区项目记忆文件列表（.agent/memory/*.md，frontmatter 元数据 + 摘要）。

        P3/P5：项目记忆不走 RAG，正文按需 read_file；此处只出索引（P5 API 用）。
        """
        return list_project_memory_files(workspace_root)


def _clamp_importance(value: float) -> float:
    """importance 钳位到 [0,1]（四处共用，Simplify 收敛）。"""
    return max(0.0, min(1.0, value))


def list_project_memory_files(workspace_root: str) -> list[dict[str, Any]]:
    """工作区项目记忆文件索引（P5 API / 提取分支共用）。

    frontmatter 元数据（type/tags/created_at/updated_at/title）+ 正文首行摘要；
    非法 md / 无 frontmatter 的行降级（title=文件名、type=note）。
    """
    from pathlib import Path

    from app.services.memory_extract import _parse_project_md

    memory_dir = Path(workspace_root) / ".agent" / "memory"
    if not memory_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for md in sorted(memory_dir.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta: dict[str, Any] = {}
        body = text
        parsed = _parse_project_md(text)
        if parsed is not None:
            meta, body = parsed
        first_line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        out.append(
            {
                "path": f".agent/memory/{md.name}",
                "name": md.stem,
                "title": str(meta.get("title") or md.stem),
                "type": str(meta.get("type") or "note"),
                "tags": meta.get("tags") or [],
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
                "summary": first_line[:120],
            }
        )
    return out


def _extract_json(text: Any) -> dict:
    """LLM 输出 → dict。剥 ```json 围栏，取首个 { 到末个 }（DeepSeek 推理模型会包 markdown）。"""
    stripped = message_text(text).strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("输出中未找到 JSON 对象")
    return json.loads(stripped[start : end + 1])


async def run_maintenance(db: Any, user_id: uuid.UUID, model: Any = None) -> dict[str, Any]:
    """LLM 整理（OA6）：读卡片+轨迹 → 计划 → 单事务应用（create/update=只增版本/delete=软删）。

    model 可注入（测试 FakeChatModel）；LLM 失败/解析失败 → 60001 retryable。
    """
    repo = MemoryRepository(db)
    cards = await repo.list_cards(user_id, limit=200)
    recent_msgs = await repo.recent_messages_for_maintenance(user_id, get_settings().memory_maintenance_limit)
    cards_text = "\n".join(
        f"- [{c.id}] ({c.card_type}, importance={c.importance:.2f}) {c.title or ''}: "
        f"{json.dumps(c.content, ensure_ascii=False)}"
        for c in cards
    )
    recent_msgs_text = "\n".join(f"- [{m.role}] {m.content[:200]}" for m in recent_msgs)
    prompt = (
        f"{_MAINTENANCE_PROMPT}\n\n当前卡片:\n{cards_text or '(无)'}\n\n"
        f"最近对话:\n{recent_msgs_text or '(无)'}"
    )
    messages = [HumanMessage(content=prompt)]
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
    try:
        # keep：显式保留（不操作）
        # update：只增新版本
        for item in plan.get("update", []) or []:
            card = await repo.get_card(user_id, uuid.UUID(str(item["id"])))
            if card is None:
                continue
            importance = float(item.get("importance", card.importance))
            await repo.add_version(card, item.get("content") or card.content, _clamp_importance(importance))
            updated += 1
        # create：新卡片（source=maintenance）
        for item in plan.get("create", []) or []:
            importance = float(item.get("importance", 0.5))
            await repo.create_card(
                user_id=user_id,
                card_type=item.get("card_type", "note"),
                content=item.get("content") or {},
                importance=_clamp_importance(importance),
                source="maintenance",
            )
            created += 1
        # delete：软删
        for card_id in plan.get("delete", []) or []:
            card = await repo.get_card(user_id, uuid.UUID(str(card_id)))
            if card is not None:
                await repo.soft_delete(card)
                deleted += 1
        # C4（原 IntegrityError 版本冲突）：文件化后无 UNIQUE 约束，commit 不抛冲突；
        # 保留 rollback 兜底（LLM 输出形状错等异常统一走下一分支）
        await db.commit()
    except (KeyError, ValueError, TypeError) as exc:
        # C2/S4：LLM 输出合法 JSON 但形状错（缺 id/UUID 非法/importance 非数字）→ 60001 retryable，不裸 500
        await db.rollback()
        raise AppError(ERR_LLM_FAILURE, f"记忆整理失败: 输出形状非法: {exc}", retryable=True) from exc
    return {
        "summary": f"整理完成：更新 {updated} 张、新建 {created} 张、删除 {deleted} 张",
        "cards_created": created,
        "cards_updated": updated,
    }
