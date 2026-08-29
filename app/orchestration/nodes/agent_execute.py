"""agent_execute 节点（docs 01 §3.1/§4）。bind_tools(ACI) + model.ainvoke 驱动 LLM 决策。

token 级流式不在此 yield：T10 用 graph.astream(stream_mode=["messages"]) 截获模型 chunk。
测试注入：config["configurable"]["model"] 可覆盖模型（mock LLM）。
run_log（type=llm）与 totals（token 累计）在此收集，T10 统一落库。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.core.cost import estimate_cost
from app.core.errors import (
    ERR_MULTIMODAL_UNSUPPORTED,
    AppError,
    LLMFailureKind,
    classify_llm_exception,
    normalize_llm_exception,
)
from app.core.llm import LLMService
from app.core.model_capabilities import (
    ModelCapabilityKey,
    VisionCapability,
    get_model_capability_resolver,
    is_explicit_vision_rejection,
)
from app.orchestration.context_builder import build_agent_tools, build_context
from app.orchestration.context_metrics import measure_context
from app.orchestration.state_schema import AgentState
from app.orchestration.stream_core import message_text


def _resolve_model(state: AgentState, config: Optional[RunnableConfig]) -> Any:  # noqa: UP045  LangGraph 需 Optional 形式
    override = (config or {}).get("configurable", {}).get("model")
    if override is not None:
        return override
    agent = state.get("agent_config", {})
    return LLMService.build_model(agent.get("model"))


def _image_ctx(config: Optional[RunnableConfig]) -> Optional[dict[str, Any]]:  # noqa: UP045
    """从 graph_config.configurable 取图片水合上下文。

    显式空键代表恢复路径：历史 ref 必须转为省略文本；完全没有图片键才走旧的无图快速路径。
    """
    if config is None:
        return None
    cfg = config.get("configurable", {}) or {}
    image_keys = {
        "image_payload",
        "current_image_ids",
        "vision",
        "image_capability_state",
        "image_capability_key",
    }
    if not image_keys.intersection(cfg):
        return None
    # Legacy callers only supplied ``vision``. Treat their explicit false as an
    # authoritative compatibility decision; the new preparation path always carries
    # the tri-state key explicitly and therefore remains optimistic for UNKNOWN.
    default_state = VisionCapability.UNKNOWN.value if cfg.get("vision") else VisionCapability.UNSUPPORTED.value
    state_raw = cfg.get("image_capability_state", default_state)
    try:
        capability = VisionCapability(state_raw)
    except (TypeError, ValueError):
        capability = VisionCapability.UNKNOWN
    key = cfg.get("image_capability_key")
    if isinstance(key, dict):
        try:
            key = ModelCapabilityKey(**key)
        except (TypeError, ValueError):
            key = None
    return {
        "index": cfg.get("image_payload") or {},
        "current_ids": set(cfg.get("current_image_ids") or []),
        "vision": bool(cfg.get("vision")),
        "capability": capability,
        "capability_key": key if isinstance(key, ModelCapabilityKey) else None,
    }


def _document_ctx(config: Optional[RunnableConfig]) -> Optional[dict[str, Any]]:  # noqa: UP045
    """从 configurable 取当前轮文档正文；正文绝不写入 AgentState/checkpoint。"""
    if config is None:
        return None
    cfg = config.get("configurable", {}) or {}
    if "document_context" not in cfg:
        return None
    context = cfg.get("document_context") or {}
    return {
        "index": context.get("index") or {},
        "current_ids": set(context.get("current_ids") or []),
    }


async def agent_execute_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    agent = state.get("agent_config", {})
    trace_id = (config or {}).get("configurable", {}).get("trace_id")

    # M2.5：两段式门控（≤ aci_full_limit 全量；超过 → tool_search + 选中注入）。
    # 每轮强制重算（不读 state.active_tools 缓存）——选中注入依赖本轮 selected_tool_names，
    # 复用旧 active_tools 会让 tool_search 结果永远进不了下一轮 bind_tools（实测坑）。
    active_tools = build_agent_tools(
        agent.get("tools", []), state.get("selected_tool_names", []), agent.get("shell_mode")
    )

    model = _resolve_model(state, config).bind_tools(active_tools)

    # 收口轮提示（2026-08-24）：接近/达到步数上限时消息通道告知 LLM 直接作答（不进 system_prompt）
    flags = dict(state.get("flags", {}))
    next_step = flags.get("steps", 0) + 1
    max_steps = int(agent.get("max_steps", 50))
    prompt_note = (
        "已到步数上限：本轮请直接给出最终答复，不要再调用工具；如需继续操作请告知用户已到达步数限制。"
        if next_step >= max_steps
        else None
    )

    start = time.perf_counter()
    image_ctx = _image_ctx(config)
    messages = build_context(
        state,
        prompt_note,
        image_ctx=image_ctx,
        document_ctx=_document_ctx(config),
    )
    context_metrics = measure_context(messages, active_tools)
    flags["context_metrics"] = context_metrics
    try:
        response = await model.ainvoke(
            messages
        )
    except Exception as exc:  # noqa: BLE001 - only explicit multimodal rejections become a typed app error
        has_current_images = bool(image_ctx and image_ctx.get("current_ids") and image_ctx.get("index"))
        capability = image_ctx.get("capability") if image_ctx else None
        key = image_ctx.get("capability_key") if image_ctx else None
        if (
            has_current_images
            and capability is not VisionCapability.UNSUPPORTED
            and isinstance(key, ModelCapabilityKey)
            and is_explicit_vision_rejection(exc)
        ):
            get_model_capability_resolver().record_unsupported(key)
            raise AppError(
                ERR_MULTIMODAL_UNSUPPORTED,
                "当前模型接口明确拒绝图片输入；图片未被分析，请更换模型或检查该接口的多模态请求格式。",
                retryable=False,
            ) from exc
        normalized = normalize_llm_exception(
            exc,
            model=str(agent.get("model") or ""),
            context_metrics=context_metrics,
        )
        # 兼容非传输调用方的异常类型；只有明确的流传输错误
        # 才转为可自动/手动恢复的 LLMTransportError。
        if classify_llm_exception(exc) is LLMFailureKind.TRANSPORT:
            raise normalized from exc
        raise exc
    if (
        image_ctx
        and image_ctx.get("capability") is VisionCapability.UNKNOWN
        and image_ctx.get("current_ids")
        and isinstance(image_ctx.get("capability_key"), ModelCapabilityKey)
    ):
        # A successful real request is stronger evidence than any name pattern or provider catalog.
        get_model_capability_resolver().record_success(image_ctx["capability_key"])
    duration_ms = int((time.perf_counter() - start) * 1000)

    # token 统计累计（totals 为 LastValue，读旧值再加）
    totals = dict(state.get("totals", {}))
    usage = getattr(response, "usage_metadata", None) or {}
    totals["prompt_tokens"] = totals.get("prompt_tokens", 0) + int(usage.get("input_tokens", 0))
    totals["completion_tokens"] = totals.get("completion_tokens", 0) + int(usage.get("output_tokens", 0))
    totals["total_tokens"] = totals.get("total_tokens", 0) + int(usage.get("total_tokens", 0))
    # 2b：成本估算（token×定价表；provider 真实账单为 M4 接缝）——totals 供 done 事件 cost 字段
    cost = estimate_cost(usage, agent.get("model", ""))
    totals["cost"] = totals.get("cost", 0.0) + cost

    flags["steps"] = next_step

    token_usage = dict(usage or {})
    token_usage["cost"] = cost
    # 把本轮 cost 随消息带出（含 usage 全量），供 stream_core 逐轮 cost 表面化（docs 03 §3 逐轮消息扩展）
    response.usage_metadata = token_usage

    return {
        "messages": [response],
        "totals": totals,
        "flags": flags,
        "run_logs": (state.get("run_logs") or [])
        + [
            {
                "node": "agent_execute",
                "type": "llm",
                "trace_id": trace_id,
                "input": {
                    "model": agent.get("model"),
                    "tool_count": len(active_tools),
                    "context_metrics": context_metrics,
                },
                "output": {"content": message_text(getattr(response, "content", ""))[:500]},
                "token_usage": token_usage,
                "duration_ms": duration_ms,
                "status": "ok",
            }
        ],
    }
