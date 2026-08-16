"""LangGraph State 定义（docs 01 §3.2）。

messages 是规范消息流（system/user/assistant/tool），add_messages reducer 负责追加与更新。
tool_results 单独存放，供 finalize 独立核对（不信任模型自述）。
flags 承载跨节点运行标记（steps 计数、max_steps 到达、status 等）。
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    # 当前启用的 Agent 配置（快照 dict，源自 agent_version）
    agent_config: dict[str, Any]
    # M2.5 两段式：tool_search 选中注入的工具名（LastValue，上限 5，由 tool_execute 写入）
    selected_tool_names: list[str]
    # M3：发起用户（memory_inject 检索范围；缺失 = 注入静默跳过）
    user_id: str
    # M3：本轮注入的长期记忆卡片（memory_inject 节点产出，build_context 渲染）
    memory_refs: list[dict[str, Any]]
    # 工具执行结果（本轮，供 finalize 校验）
    tool_results: list[dict[str, Any]]
    # 跨节点运行标记：steps / max_steps / status / context_metrics
    flags: dict[str, Any]
    # 统计：token_usage / cost
    totals: dict[str, Any]
    # 本轮 run_log 收集（T10 由 chat_stream 统一落库）。
    # LastValue：每轮开头由 initial 置 []，节点返回累计列表 → 跨轮不残留
    run_logs: list[dict[str, Any]]
    # finalize 产出的最终消息 dict（对齐 done 事件 / message 持久化）
    final_message: dict[str, Any]
    # M4：多 Agent 协作中间产物（proposer/reviewer 的草案与评审）
    drafts: dict[str, Any]
    # M4：agent_switch 事件载荷（{from_agent, to_agent, reason}，stream_core 转 SSE）
    agent_switch: dict[str, Any]
