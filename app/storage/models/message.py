"""消息实体（docs 04 §3.2 message-as-log：消息即日志，列表为权威回放源）。

tool_calls: [{tool_call_id, tool_name, input, output, status, position, duration_ms}]（对齐 mock 形状）
token_usage: {prompt_tokens, completion_tokens, total_tokens, prefix_cache_hit_tokens}
"""

import uuid
from dataclasses import dataclass, field

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class Message(Row):
    conversation_id: uuid.UUID
    role: str  # system/user/assistant/tool
    content: str = ""
    thinking: str | None = None  # 该轮推理（reasoning_content，docs 03 §3）
    attachments: list = field(default_factory=list)
    file_refs: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    token_usage: dict | None = None
    parent_id: uuid.UUID | None = None
    round: int = 1  # 轮次（docs 03 §3 逐轮消息扩展）
    trace_id: str | None = None
