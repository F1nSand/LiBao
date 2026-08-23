"""主动记忆提取分支（docs 01 §8.3）：对话流结束后的独立小推理。

职责：从本轮新增消息判定是否有值得沉淀的长期记忆——用户固定偏好/个人背景/固定约束
→ global 卡片（写入 memory_cards + 向量，P2 同步）；项目决策/迭代细节 → project md
（P3 落盘）。**不是每轮必写**：临时问题/一次性请求/会话内上下文/闲聊/模型自述 → skip。

硬性不变量：独立 LLM 调用、失败静默（记忆沉淀永不击穿对话）；由 chat_stream/task_run
的 on_final 以 asyncio.create_task 触发（不阻塞 SSE/任务流）。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from langchain_core.messages import HumanMessage

from app.core.config import get_settings
from app.core.llm import LLMService
from app.orchestration.stream_core import message_text
from app.services.memory import _extract_json
from app.storage.repositories.memory import MemoryRepository
from app.storage.repositories.run_log import RunLogRepository

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """你是记忆提取器。基于本轮对话消息，判断用户表达的内容中是否有值得沉淀为长期记忆的部分。

只提取**用户**表达的事实，绝不提取 AI 输出的内容（模型自述/建议/回答一律不记）。

值得沉淀为全局记忆（scope=global）：
- 用户自身固定偏好（如"代码尽量简洁""我习惯用 Vue3+TS""不要大段开场白"）
- 用户个人事实背景（如"我是软件工程专业，正在做 Agent 毕设"）
- 用户明确陈述的自身情况或固定约束（如"我一贯""我通常""我的情况是 XX"）

值得沉淀为项目记忆（scope=project，仅当对话属于项目工作区）：
- 项目决策、架构选择、中间过程、迭代细节、项目约定

不记（跳过，items 为空数组）：
- 临时问题、一次性请求（"帮我写一段代码""帮我算一下"这类请求本身不记）
- 会话内临时上下文（用完即丢）
- 转瞬即逝的闲聊、情绪抒发

判断要点：信息越像「永久属性」越值得记；临时任务信息自动记忆很弱。
多轮工具调用时只评估最后一条用户消息及其后的回复。

只输出 JSON，无其他文字，结构：
{"items": [{"scope": "global"|"project", "title": "简短标题", "content": "记忆内容",
 "importance": 0-1, "tags": ["标签"], "topic_key": "英文/拼音短主题名"}]}
items 可为空数组。importance 越高代表越像永久属性。"""

_MAX_TAIL = 3  # 提取输入上限：最后一条 user 及其后最多 2 条 assistant


def _messages_tail(messages: list[Any]) -> list[tuple[str, str]]:
    """提取输入：从尾部回溯到第一条 user 消息（含其后的 assistant 轮）。

    历史轮次的 user 消息在更前面，天然排除——resume/多轮对话不会重复评估旧内容。
    """
    tail: list[tuple[str, str]] = []
    for m in reversed(messages):
        if isinstance(m, dict):
            role = str(m.get("role", ""))
            content = m.get("content", "")
        else:
            role = str(getattr(m, "type", ""))
            content = getattr(m, "content", "")
        role = "user" if role in ("user", "human") else "assistant" if role in ("assistant", "ai") else ""
        if not role:
            continue
        text = message_text(content).strip()
        if not text:
            continue
        tail.append((role, text[:500]))
        if role == "user":
            break  # 回溯到用户消息为止（更早的是历史轮）
    tail.reverse()
    return tail[: _MAX_TAIL]


def _clamp_importance(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


async def _store_global_item(repo: MemoryRepository, user_id: uuid.UUID, item: dict[str, Any]) -> str:
    """global 项 → note 卡（source=extract；向量同步在 P2 于 repository 内完成）。"""
    card = await repo.create_card(
        user_id=user_id,
        card_type="note",
        content={"text": str(item.get("content", "")).strip()},
        title=item.get("title") or None,
        tags=[str(t) for t in (item.get("tags") or [])] or None,
        importance=_clamp_importance(item.get("importance")),
        source="extract",
    )
    return str(card.id)


async def _store_project_items(workspace_root: str, items: list[dict[str, Any]], trace_id: str | None) -> int:
    """project 项 → 工作区 .agent/memory/*.md（frontmatter + 同主题合并，P3 实现）。

    P1 阶段仅记录日志（提取判定先行，落盘随 P3 项目记忆文件化一并落地）。
    """
    logger.info("project memory extraction deferred to P3: %d items (ws=%s)", len(items), workspace_root)
    return 0


async def _log_extract(
    result: dict[str, Any], *, trace_id: str | None, session_id: Any, task_id: Any
) -> None:
    """提取结果落 run_log（独立任务自写；失败不抛——日志失败不影响提取结论）。"""
    try:
        await RunLogRepository().create(
            trace_id=trace_id or "",
            session_id=session_id,
            task_id=task_id,
            node="memory_extract",
            type="memory_extract",
            input={"tail": (result.get("items") or [])},
            output={
                "status": result.get("status"),
                "extracted": result.get("extracted", 0),
                "duration_ms": result.get("duration_ms", 0),
            },
            duration_ms=int(result.get("duration_ms", 0)),
            status="ok" if result.get("status") == "ok" else "error",
        )
    except Exception:  # noqa: BLE001
        logger.debug("memory extract run_log failed", exc_info=True)


async def extract_and_store(
    *,
    messages: list[Any],
    user_id: str | None,
    workspace_id: str | None = None,
    workspace_root: str | None = None,
    trace_id: str | None = None,
    session_id: Any = None,
    task_id: Any = None,
    model: Any = None,
) -> dict[str, Any]:
    """流结束后台提取：判定 → global 写卡 / project 落盘（P3）→ run_log。

    model 可注入（测试 FakeChatModel）；全异常静默返回 {"status": "error"}，
    永不向调用方抛——记忆沉淀不击穿对话。
    """
    if not get_settings().memory_extract_enabled:
        return {"status": "disabled", "extracted": 0, "duration_ms": 0}
    if not user_id:
        return {"status": "skipped", "extracted": 0, "duration_ms": 0, "reason": "no_user"}
    start = time.perf_counter()
    result: dict[str, Any] = {"status": "ok", "extracted": 0, "project_stored": 0, "items": []}
    try:
        tail = _messages_tail(messages)
        if not tail:
            result.update(status="skipped", reason="no_tail")
            return result
        prompt = _EXTRACT_PROMPT + "\n\n本轮对话:\n" + "\n".join(f"- [{r}] {t}" for r, t in tail)
        if model is None:
            model = LLMService.build_model(get_settings().memory_extract_model or None)
        response = await model.ainvoke([HumanMessage(content=prompt)])
        plan = _extract_json(getattr(response, "content", "") or "")
        items = (plan.get("items") or []) if isinstance(plan, dict) else []
        # 分类落盘：global → 卡片；project → md（需工作区）
        repo = MemoryRepository()
        global_items = [it for it in items if it.get("scope") == "global"]
        project_items = [it for it in items if it.get("scope") == "project"]
        for it in global_items:
            await _store_global_item(repo, uuid.UUID(user_id), it)
        n_project = 0
        if project_items and workspace_root:
            n_project = await _store_project_items(workspace_root, project_items, trace_id)
        result.update(
            extracted=len(global_items),
            project_stored=n_project,
            project_pending=len(project_items) - n_project,
            items=items,
            workspace_id=str(workspace_id) if workspace_id else None,
        )
    except Exception as exc:  # noqa: BLE001  提取故障不击穿对话（LLM 失败/解析失败/写卡失败）
        logger.warning("memory extract failed: %s", exc)
        result.update(status="error", error=str(exc)[:300])
    finally:
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        await _log_extract(result, trace_id=trace_id, session_id=session_id, task_id=task_id)
    return result
