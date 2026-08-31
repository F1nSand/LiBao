"""tool_execute 节点（《02》后端设计 §3.1/§7.3）。执行模型发起的工具调用 → ToolMessage + tool_results。

M2：require_confirm 工具 → interrupt() 等待人工确认（《02》后端设计 §3.4）——恢复后节点从头重执行，
interrupt() 返回 {approved: bool}；拒绝分支不执行，写 cancelled ToolMessage，LLM 接续。
每节点每轮只确认第一个 require_confirm 工具（规避 LangGraph 多 interrupt 按 id 映射的复杂度，文档化限制）。
结果 shape 对齐 《02》数据模型 §3.2 message.tool_calls（含 status：done/error/cancelled，前端读此字段）。
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.orchestration.state_schema import AgentState
from app.tools import executor
from app.tools.builtin.tool_search import selected_names
from app.tools.context import (
    CheckpointToolContext,
    set_tool_checkpoint,
    set_tool_org,
    set_tool_shell_mode,
    set_tool_user_id,
    set_tool_workspace_id,
    set_tool_workspace_root,
)
from app.tools.registry import ToolEffect, ToolGateAction, ToolGateDecision, agent_can_use, get, get_by_name


def _result(
    tc: dict,
    position: int,
    *,
    status: str,
    ok: bool,
    output: Any,
    summary: str = "",
    summary_truncated: bool = False,
    summary_original_chars: int = 0,
    duration_ms: int = 0,
    placeholder: bool = False,
    job_ref: str | None = None,
) -> dict:
    """工具结果条目（《02》数据模型 §3.2 message.tool_calls shape，三个分支共用）。"""
    return {
        "tool_call_id": tc["id"],
        "tool_name": tc["name"],
        "position": position,
        "input": tc.get("args", {}),
        "output": output,
        "ok": ok,
        "status": status,
        **({"summary": summary} if summary else {}),
        "summary_truncated": summary_truncated,
        "summary_original_chars": summary_original_chars,
        "duration_ms": duration_ms,
        # M4 完整版：占位/回填透出（initiate_* → stream_core → SSE）
        "placeholder": placeholder,
        "job_ref": job_ref,
    }


async def tool_execute_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    last = state["messages"][-1]
    trace_id = (config or {}).get("configurable", {}).get("trace_id")
    tool_msgs: list[ToolMessage] = []
    results: list[dict[str, Any]] = []
    run_logs: list[dict[str, Any]] = []
    confirmed_once = False
    state_selected: list[str] | None = None  # M2.5：本轮 tool_search 选中（None = 未触发，保留旧值）
    # M4 完整版：本轮新发起的占位任务（initiate_* 返回 placeholder+job_ref）→ 追加进 placeholder_jobs
    placeholder_jobs = list(state.get("placeholder_jobs", []))

    # 授权谓词与 acis_for_tools 共用 agent_can_use（单一不变量）。
    # I7：spec.meta 平台元工具（tool_search，无害只读发现），超限模式强制注入其 ACI，
    # 守卫同步放行（仅要求 enabled），与 build_agent_tools 的注入谓词一致。
    agent_tool_ids = set(state.get("agent_config", {}).get("tools", []) or [])
    for position, tc in enumerate(last.tool_calls or []):
        spec = get_by_name(tc["name"]) or get(tc["name"])
        meta_tool = spec is not None and spec.meta
        # 授权校验：只执行 agent 启用集内且 enabled 的工具（防模型幻觉/上下文投毒调用越权工具）
        if not (meta_tool and spec.enabled) and not agent_can_use(spec, agent_tool_ids):
            content = f"未知或未启用工具: {tc['name']}"
            tool_msgs.append(ToolMessage(content=content, tool_call_id=tc["id"]))
            results.append(_result(tc, position, status="error", ok=False, output=None))
            continue

        agent_cfg = state.get("agent_config", {})
        try:
            gate_decision = (
                spec.preflight(tc.get("args") or {}, {"shell_mode": agent_cfg.get("shell_mode")})
                if spec.preflight
                else None
            )
        except Exception as exc:  # noqa: BLE001 - policy failures fail closed per tool contract
            gate_decision = ToolGateDecision(ToolGateAction.BLOCK, f"策略预检失败: {exc}", "high")
        if gate_decision is not None and gate_decision.action == ToolGateAction.BLOCK:
            content = f"工具 {spec.name} 被安全策略拦截：{gate_decision.reason}"
            tool_msgs.append(ToolMessage(content=content, tool_call_id=tc["id"]))
            results.append(
                _result(
                    tc,
                    position,
                    status="error",
                    ok=False,
                    output={"verdict": "block", "reason": gate_decision.reason, "risk": gate_decision.risk},
                )
            )
            continue

        approved_for_call = False
        # M2：预检-确认两段式（《02》后端设计 §7.3 层③）——不可逆操作需人工确认
        needs_confirm = spec.require_confirm or (
            gate_decision is not None and gate_decision.action == ToolGateAction.CONFIRM
        )
        if needs_confirm and not confirmed_once:
            confirmed_once = True
            decision = interrupt(
                {
                    "node_id": "tool_execute",
                    "tool_call_id": tc["id"],
                    "tool_name": spec.name,
                    "input": tc.get("args", {}),
                    "reason": (
                        gate_decision.reason
                        if gate_decision is not None and gate_decision.reason
                        else f"工具 {spec.name} 为危险/不可逆操作，需人工确认后执行"
                    ),
                    "confirm_required": True,
                }
            )
            approved = bool((decision or {}).get("approved"))
            if not approved:
                content = f"用户已取消对工具 {spec.name} 的调用。"
                tool_msgs.append(ToolMessage(content=content, tool_call_id=tc["id"]))
                results.append(_result(tc, position, status="cancelled", ok=False, output=None))
                run_logs.append(
                    {
                        "node": "tool_execute",
                        "type": "tool",
                        "trace_id": trace_id,
                        "input": tc.get("args", {}),
                        "output": {"summary": "用户取消", "ok": False},
                        "duration_ms": 0,
                        "status": "cancelled",
                    }
                )
                continue
            approved_for_call = True

        # M3/M7-B/P4：请求级 org + 工作区根/ID + user 上下文（kb_search/文件/记忆工具直连存储层）
        set_tool_org(agent_cfg.get("org_id"))
        set_tool_workspace_root(agent_cfg.get("workspace_root"))
        set_tool_workspace_id(agent_cfg.get("workspace_id"))
        set_tool_user_id(state.get("user_id"))
        set_tool_shell_mode(agent_cfg.get("shell_mode"))
        config_values = (config or {}).get("configurable", {}) if config else {}
        checkpoint_context = None
        raw_checkpoint_id = config_values.get("code_checkpoint_id")
        raw_conversation_id = config_values.get("thread_id")
        workspace_root = agent_cfg.get("workspace_root")
        if spec.effect == ToolEffect.WORKSPACE_FILES and raw_checkpoint_id and raw_conversation_id and workspace_root:
            try:
                checkpoint_context = CheckpointToolContext(
                    conversation_id=uuid.UUID(str(raw_conversation_id)),
                    checkpoint_id=uuid.UUID(str(raw_checkpoint_id)),
                    workspace_root=str(workspace_root),
                    tool_call_id=str(tc["id"]),
                )
            except (AttributeError, ValueError):
                checkpoint_context = None
        set_tool_checkpoint(checkpoint_context)
        try:
            result = await executor.execute(
                spec,
                tc.get("args") or {},
                approved=approved_for_call,
                context={"shell_mode": agent_cfg.get("shell_mode")},
            )
        finally:
            set_tool_org(None)
            set_tool_workspace_root(None)
            set_tool_workspace_id(None)
            set_tool_user_id(None)
            set_tool_shell_mode(None)
            set_tool_checkpoint(None)

        # M2.5：LLM 调用元工具（tool_search）后 → 选中写入 selected_tool_names（两段式 ACI 注入）。
        # M1：空结果 → [] 清空旧选中；一轮内多次调用合并（去重保序）。契约见 tool_search.selected_names。
        if spec.meta and isinstance(result.output, dict) and "matches" in result.output:
            state_selected = list(dict.fromkeys((state_selected or []) + selected_names(result.output)))

        results.append(
            _result(
                tc,
                position,
                status="done" if result.ok else "error",
                ok=result.ok,
                output=result.output,
                summary=result.summary,
                summary_truncated=result.summary_truncated,
                summary_original_chars=result.summary_original_chars,
                duration_ms=result.duration_ms,
                placeholder=result.placeholder,
                job_ref=result.job_ref,
            )
        )
        # M4 完整版：占位任务登记（route 节点据 job_ref 回填）
        if result.placeholder and result.job_ref:
            from datetime import UTC, datetime

            placeholder_jobs.append(
                {
                    "job_ref": result.job_ref,
                    "tool_call_id": tc["id"],
                    "tool_name": spec.name,
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
        content = result.summary if result.ok else f"错误: {result.error}"
        tool_msgs.append(ToolMessage(content=content, tool_call_id=tc["id"]))
        run_logs.append(
            {
                "node": "tool_execute",
                "type": "tool",
                "trace_id": trace_id,
                "input": tc.get("args", {}),
                "output": {"summary": result.summary[:500], "ok": result.ok, "error": result.error},
                "duration_ms": result.duration_ms,
                # 《02》数据模型 run_log.status：retried（重试后成功）/ ok / error
                "status": "retried" if result.retries > 0 and result.ok else ("ok" if result.ok else "error"),
            }
        )

    return {
        "messages": tool_msgs,
        "tool_results": results,
        "run_logs": (state.get("run_logs") or []) + run_logs,
        # LastValue：本轮有 tool_search 结果才更新，否则保留旧选中
        "selected_tool_names": state_selected if state_selected is not None else state.get("selected_tool_names", []),
        "placeholder_jobs": placeholder_jobs,
    }
