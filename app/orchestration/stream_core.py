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
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage

from app.core.errors import ERR_LLM_FAILURE
from app.tools.context import set_dispatch_ctx
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


def _build_round_message(round_data: dict[str, Any], tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    """逐轮消息（docs 03 §3）：content 剥 thinking + thinking(reasoning_content) + 该轮 tool_calls + round。"""
    by_id = {r.get("tool_call_id"): r for r in tool_results}
    tool_calls = []
    for tc in round_data["tool_calls"]:
        full = by_id.get(tc.get("id"))
        if full is not None:
            tool_calls.append(full)
    return {
        "role": "assistant",
        "content": message_text(round_data["content"]),
        "thinking": round_data.get("thinking") or "",
        "tool_calls": tool_calls,
        "round": round_data["round"],
    }


def build_initial_state(
    agent: Any,
    content: str,
    user_id: str | None = None,
    org_id: str | None = None,
    enabled_tool_ids: list[str] | None = None,
) -> dict[str, Any]:
    """图初始状态（chat/invoke/task 共用）：messages + agent_config + LastValue 轮次通道重置。

    user_id/org_id 供 M3 memory_inject（注入）与 kb_search 工具（org 上下文）使用；
    缺失时注入静默跳过（不击穿对话）。

    单通用 Agent 有效工具集 = seed 精选（agent.tools）∪ 本组织已启用工具（enabled_tool_ids）——
    MCP/自定义工具启用后即对通用助手开放（约束优先：仍要求 spec.enabled，tool_execute 守卫同源）。
    """
    seed_tools = set(agent.tools or [])
    if enabled_tool_ids:
        seed_tools |= set(enabled_tool_ids)
    return {
        "messages": [HumanMessage(content=content)],
        "agent_config": {
            "name": agent.name,
            "model": agent.model,
            "system_prompt": agent.system_prompt,
            "tools": sorted(seed_tools),  # 确定性排序（前缀稳定；启停实时生效）
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
    round_sink: list[dict[str, Any]] | None = None,
    on_round_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    """驱动 graph.astream → SSE 帧。

    - on_interrupt(value)：中断时回调（返回 SSE 帧或 None），随后流结束；
    - on_final(final_state)：正常结束回调（返回 done payload dict 或 None）；
    - on_error(exc)：图级异常回调（后台运行器用它把任务置 failed）。
    - round_sink：逐轮消息收集（docs 03 §3 多消息扩展）——每轮工具结果齐后 emit `message` 事件，
      并把该轮消息（含 id/content/tool_calls/round）append 进 sink；on_final 据此补最终轮（id 一致）。
    - on_round_message：每轮工具结果齐后同步落库回调（即时落库：任务中 DB 已有已完成轮次，
      前端轨迹轮询/切会话即见）；on_final 不再重复落已落库轮次。
    """
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    # M4.5：subagent 派发事件汇（tl_dispatch_subagent 在 producer 内跑嵌套循环时，
    # 经 push 把 emit 帧投进本队列，由主循环 yield 出去——chat 转 SSE / task 转事件）。
    def _push(event_type: str, payload: dict[str, Any]) -> str:
        queue.put_nowait(("frame", emit(event_type, payload)))
        return ""

    # resume 路径 initial 是 Command(resume=...) 对象（非 dict）——只从 dict 读取主 agent 名
    _main_name = "通用助手"
    if isinstance(initial, dict):
        _main_name = str((initial.get("agent_config", {}) or {}).get("name", _main_name))
    _thread_key = str((graph_config.get("configurable") or {}).get("thread_id", ""))
    set_dispatch_ctx({"push": _push, "main_name": _main_name, "thread_key": _thread_key})

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
    # 逐轮消息（docs 03 §3）：round_seq 计数；pending_round = 本轮 agent_execute 的 AIMessage（有 tool_calls）
    round_seq = 0
    pending_round: dict[str, Any] | None = None

    async def _emit_round(round_msg: dict[str, Any]) -> str:
        """逐轮消息封口：生成 id → append sink → 即时落库（on_round_message）→ 发 `message` 事件。"""
        msg_id = str(uuid.uuid4())
        round_msg["id"] = msg_id
        if round_sink is not None:
            round_sink.append(round_msg)
        if on_round_message is not None:
            await on_round_message(round_msg)
        return emit("message", {"message_id": msg_id, "message": round_msg})

    try:
        while True:
            kind, payload = await queue.get()
            if kind == "keepalive":
                yield ": keepalive\n\n"
                continue
            if kind == "frame":
                # subagent 派发事件帧（dispatch_subagent push 进队列）
                yield payload
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
                    # 推理增量（DeepSeek reasoning_content；docs 03 §3 thinking 事件，前端累积到一轮一条）
                    rc = (getattr(chunk, "additional_kwargs", {}) or {}).get("reasoning_content")
                    if rc:
                        yield emit("thinking", {"text": rc, "ts": int(time.time() * 1000)})
            elif mode == "updates":
                for node, update in item.items():
                    if node == "agent_execute":
                        for m in update.get("messages", []):
                            tcs = getattr(m, "tool_calls", None) or []
                            if tcs:
                                pending_round = {
                                    "content": m.content,
                                    "tool_calls": [dict(tc) for tc in tcs],
                                    "round": round_seq + 1,
                                    "thinking": (getattr(m, "additional_kwargs", {}) or {}).get(
                                        "reasoning_content"
                                    )
                                    or "",
                                }
                            for tc in tcs:
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
                                    # M4 完整版：透出占位/回填真值（initiate_* 占位卡 → 回填真值卡）
                                    "placeholder": bool(r.get("placeholder", False)),
                                    "job_ref": r.get("job_ref"),
                                    "duration_ms": r.get("duration_ms", 0),
                                },
                            )
                        # 逐轮消息封口（docs 03 §3）：本轮工具结果齐后发 `message` 事件（前端追加独立消息 + sealRound）
                        if pending_round is not None:
                            round_seq += 1
                            yield await _emit_round(
                                _build_round_message(pending_round, update.get("tool_results", []))
                            )
                            pending_round = None
                        else:
                            # resume 中断轮：本轮 AI 消息在中断前（本流不可见），仅用工具结果构建轮消息（content 空；
                            # 含 cancelled 拒绝分支——该轮尝试了工具）
                            tcs = list(update.get("tool_results", []))
                            if tcs:
                                round_seq += 1
                                yield await _emit_round(
                                    {
                                        "role": "assistant",
                                        "content": "",
                                        "thinking": "",
                                        "tool_calls": tcs,
                                        "round": round_seq,
                                    }
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
        set_dispatch_ctx(None)  # 清事件汇（task-local，防串）
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
