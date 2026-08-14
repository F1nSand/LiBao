"""任务 schema（docs 03 §5.3）。resume 载荷：{confirm: {approved: bool}}（OB4 统一）。"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel


class SubmitTaskRequest(BaseModel):
    agent_id: uuid.UUID
    input: dict[str, Any] = {}
    params: dict[str, Any] | None = None


class TaskResumeRequest(BaseModel):
    confirm: dict[str, Any] | None = None
