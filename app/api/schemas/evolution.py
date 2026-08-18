"""进化闭环·候选区请求 schema（docs 03 §5.13）。手动创建入口（前端无，供测试/演示）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ChangeType = Literal["prompt", "skill", "tool", "memory", "context"]


class CreateCandidateRequest(BaseModel):
    title: str
    change_type: ChangeType
    evidence: str | None = None
    root_cause: str | None = None
    proposed_change: str | None = None
    expected_fix: str | None = None
    affected_behaviors: list[str] | None = None
    validation_cases: list[dict] | None = None
