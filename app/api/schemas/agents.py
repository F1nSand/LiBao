"""Agent 写 schema（docs 03 §5.4）。创建/更新共用；字段全可选，create 时服务层校验 name/model。"""
from __future__ import annotations

from pydantic import BaseModel


class AgentWriteRequest(BaseModel):
    name: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    skills: list[str] | None = None
    tools: list[str] | None = None
    graph_template: str | None = None
    max_steps: int | None = None
