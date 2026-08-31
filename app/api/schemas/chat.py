"""对话流式 schema（《02》接口契约 §5.2 ChatRequest）。content 超 32K → 40014（OC1）。"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.errors import ERR_INPUT_TOO_LONG, AppError

CONTENT_LIMIT = 32000
MAX_SOURCES = 10


class FileRef(BaseModel):
    """工作区内的相对文件引用。

    路径是否存在、是否越出当前工作区以及是否为普通文件由服务层在拿到
    workspace_id 后再次校验；schema 层只做形状与长度约束，避免把真实路径
    状态泄露为不同的 HTTP 响应。
    """

    path: str = Field(min_length=1, max_length=1024)
    model_config = ConfigDict(extra="forbid")

    @field_validator("path")
    @classmethod
    def _path_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("path 不能为空")
        return value


class ChatMessageInput(BaseModel):
    content: str
    role: Literal["user"] = "user"
    # S9：附件 ID 用 uuid 类型校验，非法值由 pydantic 返回 422（此前路由 uuid.UUID(aid) 裸抛 500）
    attachments: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_SOURCES)
    file_refs: list[FileRef] = Field(default_factory=list, max_length=MAX_SOURCES)

    @field_validator("content")
    @classmethod
    def _limit(cls, value: str) -> str:
        if len(value) > CONTENT_LIMIT:
            raise AppError(ERR_INPUT_TOO_LONG, f"输入超长（>{CONTENT_LIMIT} 字符）")
        return value


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None  # 工作区对话（M7-B）：项目级 agent + 文件工具
    message: ChatMessageInput
    stream: bool = True
