"""任务 schema（《02》接口契约 §5.3）。resume 载荷：{confirm: {approved: bool}}（OB4 统一）。
单通用 Agent：提交不再接收 agent_id（服务端用默认通用 Agent）。"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.api.schemas.chat import CONTENT_LIMIT


class SubmitTaskRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] | None = None

    @field_validator("input")
    @classmethod
    def normalize_input(cls, value: dict[str, Any]) -> dict[str, Any]:
        data = dict(value)
        if "message" in data:
            message = data["message"]
            if not isinstance(message, str):
                raise ValueError("input.message 必须是字符串")
            if len(message) > CONTENT_LIMIT:
                raise ValueError(f"input.message 超长（>{CONTENT_LIMIT} 字符）")
        if "attachment_ids" in data:
            attachment_ids = data["attachment_ids"]
            if not isinstance(attachment_ids, list):
                raise ValueError("input.attachment_ids 必须是列表")
            normalized: list[str] = []
            for attachment_id in attachment_ids:
                try:
                    normalized.append(str(uuid.UUID(str(attachment_id))))
                except (AttributeError, ValueError) as exc:
                    raise ValueError("input.attachment_ids 包含无效 UUID") from exc
            data["attachment_ids"] = normalized
        return data


class TaskResumeRequest(BaseModel):
    confirm: dict[str, Any] | None = None


class TaskRecoverRequest(BaseModel):
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=8, max_length=128)
