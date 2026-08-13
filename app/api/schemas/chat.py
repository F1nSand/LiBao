"""对话流式 schema（docs 03 §5.2 ChatRequest）。content 超 32K → 40014（OC1）。"""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, field_validator

from app.core.errors import ERR_INPUT_TOO_LONG, AppError

CONTENT_LIMIT = 32000


class ChatMessageInput(BaseModel):
    content: str
    role: Literal["user"] = "user"
    attachments: list[str] = []

    @field_validator("content")
    @classmethod
    def _limit(cls, value: str) -> str:
        if len(value) > CONTENT_LIMIT:
            raise AppError(ERR_INPUT_TOO_LONG, f"输入超长（>{CONTENT_LIMIT} 字符）")
        return value


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    agent_id: uuid.UUID
    message: ChatMessageInput
    stream: bool = True
