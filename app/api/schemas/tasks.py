"""任务 schema（docs 03 §5.3）。resume 载荷：{confirm: {approved: bool}}（OB4 统一）。
单通用 Agent：提交不再接收 agent_id（服务端用默认通用 Agent）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SubmitTaskRequest(BaseModel):
    input: dict[str, Any] = {}
    params: dict[str, Any] | None = None


class TaskResumeRequest(BaseModel):
    confirm: dict[str, Any] | None = None
