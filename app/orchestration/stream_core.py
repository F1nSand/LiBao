"""Graph→SSE 事件映射共享循环（docs 01 §5.2 / docs 03 §3.3）。

单次运行（chat_stream_events）与恢复续流（resume_stream_events）共用同一循环：
producer/queue/keepalive + messages/updates/values 三模式映射。
M2 扩展：tool_call.require_confirm 取自 spec；拒绝分支（status=cancelled）不发 tool_result；
__interrupt__ 分支 → on_interrupt 落 Task + 发 interrupt 事件后结束流（等 resume）。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from langchain_core.messages import HumanMessage

from app.core.errors import ERR_LLM_FAILURE
from app.tools.registry import get, get_by_name

logger = logging.getLogger(__name__)

KEEPALIVE_INTERVAL = 15


def message_text(content: Any) -> str:
    """消息文本提取（兼容 str 或 content blocks 列表；跳过 thinking 块，
    保留裸字符串块——DeepSeek v4-flash 会把最终输出放在末位裸 str 块）。"""
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


def _chunk_text(chunk: Any) -> str:
    """从 AIMessageChunk 提取 text（流式增量块；兼容 str 或 content blocks）。"""
    return message_text(getattr(chunk, "content", ""))


def build_initial_state(
    agent: Any, content: str, user_id: str | None = None, org_id: str | None = None
) -> dict[str, Any]:
    """图初始状态（chat/invoke/task 共用）：messages + agent_config + LastValue 轮次通道重置。

    user_id/org_id 供 M3 memory_inject（注入）与 kb_search 工具（org 上下文）使用；
    缺失时注入静默跳过（不击穿对话）。
    """
    return {
        "messages": [HumanMessage(content=content)],
        "agent_config": {
            "model": agent.model,
            "system_prompt": agent.system_prompt,
            "tools": agent.tools or [],
            "max_steps": agent.max_steps,
            "org_id": org_id or str(getattr(agent, "org_id", "") or ""),
        },
        "user_id": user_id,
        # LastValue 通道需每轮显式重置，否则跨轮 checkpoint 残留上轮 tool_results/run_logs
        "flags": {"steps": 0},
        "tool_results": [],
        "run_logs": [],
    }


async def stream_graph_events(
    *,
    graph: Any,
    initial: Any,
    graph_config: dict[str, Any],
    emit: Callable[[str, dict[str, Any]], str],
    on_interrupt: Callable[[dict[str, Any]], Any] | None = None,
    on_final: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    on_error: Callable[[Exception], Any] | None = None,
    keepalive_interval: int = KEEPALIVE_INTERVAL,
) -> AsyncIterator[str]:
    """驱动 graph.astream → SSE 帧。

    - on_interrupt(value)：中断时回调（返回 SSE 帧或 None），随后流结束；
    - on_final(final_state)：正常结束回调（返回 done payload dict 或 None）；
    - on_error(exc)：图级异常回调（后台运行器用它把任务置 failed）。
    """
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    async def producer() -> None:
        try:
            async for item in graph.astream(initial, graph_config, stream_mode=["messages", "updates", "values"]):
                await queue.put(("item", item))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("graph stream failed")
            await queue.put(("graph_error", exc))
        finally:
            await queue.put(("eof", None))

    async def keepalive() -> None:
        try:
            while True:
                await asyncio.sleep(keepalive_interval)
                await queue.put(("keepalive", None))
        except asyncio.CancelledError:
            pass

    producer_task = asyncio.create_task(producer())
    keepalive_task = asyncio.create_task(keepalive())
    final_state: dict[str, Any] | None = None
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "keepalive":
                yield ": keepalive\n\n"
                continue
            if kind == "eof":
                break
            if kind == "graph_error":
                if on_error is not None:
                    await on_error(payload)
                yield emit("error", {"code": ERR_LLM_FAILURE, "message": str(payload), "retryable": False})
                return

            mode, item = payload
            if mode == "messages":
                chunk, meta = item
                if meta.get("langgraph_node") == "agent_execute":
                    text = _chunk_text(chunk)
                    if text:
                        yield emit("token", {"text": text})
            elif mode == "updates":
                for node, update in item.items():
                    if node == "agent_execute":
                        for m in update.get("messages", []):
                            for tc in getattr(m, "tool_calls", []) or []:
                                spec = get_by_name(tc["name"]) or get(tc["name"])
                                yield emit(
                                    "tool_call",
                                    {
                                        "tool_call_id": tc["id"],
                                        "tool_name": tc["name"],
                                        "input": tc.get("args", {}),
                                        "require_confirm": bool(spec is not None and spec.require_confirm),
                                    },
                                )
                    elif node == "tool_execute":
                        for r in update.get("tool_results", []):
                            if r.get("status") == "cancelled":
                                continue  # 拒绝分支不发 tool_result（前端卡片停留 awaiting_confirm）
                            yield emit(
                                "tool_result",
                                {
                                    "tool_call_id": r.get("tool_call_id"),
                                    "tool_name": r.get("tool_name"),
                                    "ok": r.get("ok"),
                                    "summary": r.get("summary", ""),
                                    "structured": r.get("output"),
                                    "placeholder": False,
                                    "job_ref": None,
                                    "duration_ms": r.get("duration_ms", 0),
                                },
                            )
                    elif node == "context_update":
                        yield emit("status", {"status": "finalizing", "context_metrics": None})
                    elif node == "__interrupt__":
                        value = update[0].value
                        if on_interrupt is not None:
                            frame = await on_interrupt(value)
                            if frame:
                                yield frame
                        return  # 中断：流结束（等待 resume）
            elif mode == "values":
                final_state = item
    finally:
        producer_task.cancel()
        keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer_task
            await keepalive_task

    if final_state is not None and on_final is not None:
        # C3：on_final（落库）失败不得穿出——否则 assistant 消息 + done 帧丢失、resume 任务卡 running。
        # 走 on_error 兜底（后台运行器用它置任务 failed），再发 error 帧结束流。
        try:
            payload = await on_final(final_state)
        except Exception as exc:  # noqa: BLE001
            logger.exception("on_final failed")
            if on_error is not None:
                with contextlib.suppress(Exception):
                    await on_error(exc)
            yield emit("error", {"code": ERR_LLM_FAILURE, "message": str(exc), "retryable": True})
            return
        if payload:
            yield emit("done", payload)
