"""会话 schema（docs 03 §5.2）。单通用 Agent：新建会话不再接收 agent_id。"""
from __future__ import annotations

from pydantic import BaseModel


class CreateConversationRequest(BaseModel):
    title: str = "新会话"
