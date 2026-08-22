"""tl_dispatch_subagent 内置工具（docs 01 §3.5）：主 Agent 自主派发 subagent（Claude Code 式）。

handler 内跑嵌套 LLM 循环：
- 子 agent 独立 prompt + 独立工具集（bind_tools(subagent_acis)），上下文隔离（只传任务+补充事实）；
- 子工具经现有 executor.execute 执行（校验/超时/重试/幂等/ToolResult 全复用）；
- 结果（最终文本）作为工具返回值回主 Agent 收口；期间经 dispatch ctx 发 agent_switch 事件
  （进入 subagent / 离开 subagent；chat 路径转发 SSE，task 路径转发任务事件）。

dispatch ctx（app/tools/context.py get_dispatch_ctx）由 stream_graph_events 设置：
{push, model_builder?, main_name}。测试用 model_builder 注入假模型。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.registry import SubagentSpec, get_subagent, subagent_acis, subagent_names
from app.core.llm import LLMService
from app.tools import executor
from app.tools.context import get_dispatch_ctx
from app.tools.registry import ToolSpec, get, get_by_name

logger = logging.getLogger(__name__)


def _text(content: Any) -> str:
    """subagent 最终回复文本提取（非流式 ainvoke，content 通常为 str；兼容 content blocks）。"""
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


async def _run_subagent(
    spec: SubagentSpec, task: str, context: str | None, ctx: dict[str, Any] | None
) -> dict[str, Any]:
    """嵌套 LLM 循环：子 agent 独立 prompt+tools，工具结果回填，直至无 tool_calls 或达 max_steps。"""
    model_builder = (ctx or {}).get("model_builder") or LLMService.build_model
    model = model_builder(spec.model)
    acis = subagent_acis(spec)
    bound = model.bind_tools(acis) if acis else model

    messages: list[BaseMessage] = [SystemMessage(content=spec.prompt), HumanMessage(content=task)]
    if context:
        messages.append(HumanMessage(content=f"补充事实/上下文（来自主 Agent）：\n{context}"))

    resp: AIMessage | None = None
    steps = 0
    tool_calls_total = 0
    for step in range(1, spec.max_steps + 1):
        steps = step
        resp = await bound.ainvoke(messages)
        calls = getattr(resp, "tool_calls", None) or []
        if not calls:
            break
        tool_calls_total += len(calls)
        tool_msgs: list[ToolMessage] = []
        for tc in calls:
            t: ToolSpec | None = get_by_name(tc.get("name") or "") or get(tc.get("name") or "")
            if t is None:
                tool_msgs.append(ToolMessage(content=f"未知工具: {tc.get('name')}", tool_call_id=tc.get("id", "")))
                continue
            result = await executor.execute(t, tc.get("args") or {})
            content = result.summary if result.ok else f"错误: {result.error}"
            tool_msgs.append(ToolMessage(content=content, tool_call_id=tc.get("id", "")))
        messages.append(resp)
        messages.extend(tool_msgs)

    output = _text(resp.content) if resp is not None else "(无输出)"
    return {"output": output, "subagent": spec.name, "steps": steps, "tool_calls": tool_calls_total}


async def dispatch_subagent_handler(subagent: str, task: str, context: str | None = None) -> dict[str, Any]:
    """主 Agent 派发 subagent：{subagent, task, context?} → {output, subagent, steps, tool_calls} 或 error。"""
    spec = get_subagent(subagent)
    if spec is None:
        return {"error": f"未知 subagent: {subagent}（可选: {subagent_names()}）"}

    ctx = get_dispatch_ctx() or {}
    push = ctx.get("push")
    main_name = ctx.get("main_name") or "通用助手"
    if push is not None:
        try:
            push("agent_switch", {"from_agent": main_name, "to_agent": spec.name, "reason": task[:200]})
        except Exception as exc:  # noqa: BLE001  事件发射失败不阻断派发
            logger.warning("dispatch agent_switch(start) emit failed: %s", exc)

    try:
        result = await _run_subagent(spec, task, context, ctx)
    except Exception as exc:  # noqa: BLE001  subagent 失败回传错误信息（主 Agent 可降级应答）
        logger.exception("subagent %s failed", spec.name)
        result = {"error": f"subagent {spec.name} 执行失败: {str(exc)[:300]}", "subagent": spec.name}

    if push is not None:
        try:
            push("agent_switch", {"from_agent": spec.name, "to_agent": main_name, "reason": "子任务完成"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("dispatch agent_switch(end) emit failed: %s", exc)
    return result
