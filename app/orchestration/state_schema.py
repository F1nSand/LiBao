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
    # P3：项目记忆/知识索引（工作区 .agent/memory|knowledge 文件名+摘要；不进 system_prompt，
    # build_context 渲染为尾部 SystemMessage，agent 细节按需 read_file）
    project_memory_index: str | None
    # 工作区/项目级叠加（[工作区] system_prompt_fragment + [项目约定] agent.md + skills 路由段）。
    # 前缀缓存铁律：不进 system_prompt（曾拼入 → 按工作区变化破坏跨会话前缀缓存，2026-08-24 改），
    # build_context 渲染为历史后 SystemMessage。
    project_overlay: str | None
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
    # M4 完整版：轮边界排空的安全点事件（route 裁决后待渲染给模型，context_update 消费）
    pending_events: list[dict[str, Any]]
    # M4 完整版：本会话在途的占位任务（{job_ref, tool_call_id, tool_name, created_at}，initiate_* 写入、
    # 回填命中后移除）——回填 tool_result 的 job_ref 匹配依据
    placeholder_jobs: list[dict[str, Any]]
