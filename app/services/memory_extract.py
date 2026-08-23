"""主动记忆提取分支（docs 01 §8.3）：对话流结束后的独立小推理。

职责：从本轮新增消息判定是否有值得沉淀的长期记忆——用户固定偏好/个人背景/固定约束
→ global 卡片（写入 memory_cards + 向量，P2 同步）；项目决策/迭代细节 → project md
（P3 落盘）。**不是每轮必写**：临时问题/一次性请求/会话内上下文/闲聊/模型自述 → skip。

硬性不变量：独立 LLM 调用、失败静默（记忆沉淀永不击穿对话）；由 chat_stream/task_run
的 on_final 以 asyncio.create_task 触发（不阻塞 SSE/任务流）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from app.core.config import get_settings
from app.core.llm import LLMService
from app.core.messages import message_text  # 独立模块（防 stream_core 导入环）
from app.services.memory import _extract_json
from app.storage.repositories.memory import MemoryRepository
from app.storage.repositories.run_log import RunLogRepository

logger = logging.getLogger(__name__)

# 后台提取任务强引用集（review C3：asyncio.create_task 弱引用 + 提取含秒级 LLM 调用，
# 无强引用可能被周期性 GC 回收 → "Task was destroyed" 静默中断）
_EXTRACT_TASKS: set[asyncio.Task] = set()


def spawn_extract(coro: Any) -> None:
    """spawn 提取任务并持引用（done 后自动释放；best-effort 不阻塞调用方）。"""
    task = asyncio.create_task(coro)
    _EXTRACT_TASKS.add(task)
    task.add_done_callback(_EXTRACT_TASKS.discard)

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
 "importance": 0-1, "tags": ["标签"], "topic_key": "英文/拼音短主题名",
 "type": "decision|fact|progress|note"}]}
items 可为空数组。importance 越高代表越像永久属性。type 仅 project 项需要
（decision=决策、fact=事实、progress=迭代进展、note=其他记录）。"""

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
    """project 项 → 工作区 `.agent/memory/*.md`（frontmatter + 同主题合并更新）。

    文件组织：每主题/决策一文件 `{topic_key}.md`；已有同 topic_key（frontmatter 匹配）
    → 追加「更新记录」段 + 刷新 updated_at；否则新建。单个文件写失败不影响其余。
    """
    stored = 0
    for item in items:
        try:
            if await _write_project_md(workspace_root, item, trace_id):
                stored += 1
        except Exception as exc:  # noqa: BLE001  单个项目项写失败不影响其余
            logger.warning("project memory write failed: %s", exc)
    return stored


# ---- 项目记忆 md 文件（P3：工作区 .agent/memory/，frontmatter + 同主题合并）----

_PROJECT_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_PROJECT_LOCK: dict[str, asyncio.Lock] = {}
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\s]+')


def _slugify(text: str) -> str:
    """topic_key/title → 安全文件名（非法字符折叠为下划线，空退化为 memory）。"""
    slug = _INVALID_FILENAME_CHARS.sub("_", text.strip()).strip("_")
    return slug or "memory"


def _parse_project_md(text: str) -> tuple[dict[str, str], str] | None:
    """解析已落盘 md → (meta, body)；无 frontmatter 返回 None。"""
    m = _PROJECT_FRONTMATTER_RE.match(text)
    if m is None:
        return None
    import yaml

    try:
        meta = yaml.safe_load(m.group(1))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(meta, dict):
        return None
    return {str(k): v for k, v in meta.items()}, (m.group(2) or "").strip()


def _render_project_md(meta: dict[str, Any], body: str) -> str:
    """meta + body → md（YAML frontmatter + 空行 + 正文）。"""
    import yaml

    fm = yaml.safe_dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


async def _write_project_md(workspace_root: str, item: dict[str, Any], trace_id: str | None) -> bool:
    """写/合并单个项目记忆项（asyncio 锁防并发；读-改-写原子）。"""
    memory_dir = Path(workspace_root) / ".agent" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    topic_key = _slugify(item.get("topic_key") or item.get("title") or "memory")
    path = memory_dir / f"{topic_key}.md"
    now = datetime.now(UTC).isoformat(timespec="seconds")
    lock = _PROJECT_LOCK.setdefault(str(path), asyncio.Lock())
    async with lock:
        body = str(item.get("content", "")).strip()
        existing = None
        try:
            existing = _parse_project_md(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            existing = None
        if existing is not None and str(existing[0].get("topic_key", "")) == topic_key:
            # 同主题合并：追加更新记录 + 刷新 updated_at / 来源
            meta, prev_body = existing
            meta["updated_at"] = now
            if trace_id:
                meta["source_conversation"] = trace_id
            merged = f"{prev_body}\n\n## {now[:10]} 更新\n\n{body}"
            path.write_text(_render_project_md(meta, merged), encoding="utf-8")
        else:
            meta = {
                "type": str(item.get("type") or "note"),
                "title": str(item.get("title") or topic_key),
                "topic_key": topic_key,
                "created_at": now,
                "updated_at": now,
                "tags": [str(t) for t in (item.get("tags") or [])],
                "source_conversation": trace_id or "",
            }
            path.write_text(_render_project_md(meta, body), encoding="utf-8")
    return True


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
        if global_items:
            # C1-review：显式 commit——提取是独立后台任务，不依赖请求侧 FileContext.commit
            # （否则卡片只在内存，重启/任意外部 rollback 即丢；版本 JSONL 与向量成孤儿）
            from app.storage.file.store import FileContext, get_store

            await FileContext(get_store()).commit()
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
