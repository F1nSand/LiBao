"""会话 schema（docs 03 §5.2）。"""
from __future__ import annotations

import uuid

from pydantic import BaseModel


class CreateConversationRequest(BaseModel):
    title: str = "新会话"
    agent_id: uuid.UUID
