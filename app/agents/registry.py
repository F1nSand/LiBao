"""内置 subagent 注册表（docs 01 §3.5 单主 Agent 派发 subagent）。

与 Claude Code 的 subagent 同构：每个 subagent = 独立 prompt + 独立工具集 + 上下文隔离
（主 Agent 只传「任务描述 + 已确认事实 + 文件路径」，subagent 只回传结论）。
内置注册表（代码定义）；用户自建 subagent / 工作流属于后续「工作区」项目（docs 07）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tools.registry import ToolSpec, get, get_by_name

RESEARCH_PROMPT = (
    "你是「资料调研」subagent。任务：检索知识库（kb_search）与抓取网页（fetch_url）收集事实，"
    "输出结构化结论：{主要发现}{关键数据}{来源列表}。只做资料收集与归纳，不做无关发挥；"
    "不确定的事实标注『待核实』。结果将交回主 agent 继续回答用户。"
)

CODE_REVIEW_PROMPT = (
    "你是「代码评审」subagent。任务：审查给出的代码（可直接分析任务文本中的代码，或用 fetch_url 抓取远程代码），"
    "输出：{功能正确性问题}{安全风险}{可读性/改进建议}，按严重度排序并给出具体行级建议。"
    "结论将交回主 agent 继续回答用户。"
)

PROPOSAL_REVIEW_PROMPT = (
    "你是「方案评审」subagent。任务：对给出的方案/计划做批判性评审，输出：{可行性评估}{主要风险}"
    "{遗漏点}{更优替代方案}。需要时可用 kb_search 检索知识库佐证。结论将交回主 agent 继续回答用户。"
)


@dataclass(frozen=True)
class SubagentSpec:
    name: str
    description: str  # 给主 Agent 看：何时派发（dispatch_subagent 参数枚举）
    prompt: str
    tools: tuple[str, ...] = ()
    max_steps: int = 6
    model: str | None = None  # 缺省用主 Agent 模型


SUBAGENTS: tuple[SubagentSpec, ...] = (
    SubagentSpec(
        name="research",
        description="资料调研：检索知识库/抓取网页汇总事实与结论。需要查资料、汇总信息时派发。",
        prompt=RESEARCH_PROMPT,
        tools=("tl_kb_search", "tl_fetch_url", "tl_tool_search"),
    ),
    SubagentSpec(
        name="code_review",
        description="代码评审：审查代码片段或远程代码，列缺陷/安全风险/改进建议。需要审查代码时派发。",
        prompt=CODE_REVIEW_PROMPT,
        tools=("tl_fetch_url", "tl_tool_search"),
    ),
    SubagentSpec(
        name="proposal_review",
        description="方案评审：批判性评审方案/计划（可行性/风险/遗漏/更优解）。需要评审方案时派发。",
        prompt=PROPOSAL_REVIEW_PROMPT,
        tools=("tl_kb_search",),
    ),
)

_BY_NAME: dict[str, SubagentSpec] = {s.name: s for s in SUBAGENTS}


def get_subagent(name: str) -> SubagentSpec | None:
    return _BY_NAME.get(name)


def subagent_names() -> list[str]:
    return [s.name for s in SUBAGENTS]


def subagent_acis(spec: SubagentSpec) -> list[dict[str, Any]]:
    """subagent 的工具 ACI 列表（供 bind_tools）。缺 id 的工具静默跳过（不击穿派发）。"""
    acis: list[dict[str, Any]] = []
    for tid in spec.tools:
        t: ToolSpec | None = get(tid) or get_by_name(tid)
        if t is not None and t.enabled:
            acis.append(t.aci())
    return acis
