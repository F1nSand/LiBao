"""Agent 配置与其版本快照（docs 04 §3.4）。

agent_version 保存每次发布快照（append-only），prefix_hash 为静态前缀缓存键（docs 01 §4.1）。
单通用 Agent 模型（docs 01 §3.5）：一条 is_default=True 的通用 Agent，不再配置多 Agent/自选；
subagent 由主 Agent 经 tl_dispatch_subagent 自主派发（内置注册表，非 agent_configs 行）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class AgentConfig(Row):
    org_id: uuid.UUID
    name: str
    model: str
    system_prompt: str = ""
    is_default: bool = False
    skills: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    max_steps: int = 50
    status: str = "draft"  # draft/published/disabled
    current_version: int = 0


@dataclass(kw_only=True)
class AgentVersion(Row):
    agent_id: uuid.UUID
    version: int
    system_prompt: str = ""
    model: str = ""
    tools: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    prefix_hash: str | None = None
