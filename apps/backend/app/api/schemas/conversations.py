"""会话 schema（《02》接口契约 §5.2）。单通用 Agent：新建会话不再接收 agent_id。"""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class CreateConversationRequest(BaseModel):
    title: str = "新会话"
    workspace_id: uuid.UUID | None = None  # 工作区会话（M7-B）；null=普通会话
