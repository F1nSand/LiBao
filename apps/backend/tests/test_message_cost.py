"""M6-2 逐轮 cost 表面化测试（纯单元）：serialize_message 加 cost，token_usage 缺省兜底 0.0。"""
from __future__ import annotations

import uuid

from app.services.serializers import serialize_message
from app.storage.models.message import Message


def _msg(token_usage) -> Message:
    return Message(
        id=uuid.uuid4(), conversation_id=uuid.uuid4(), role="assistant", content="hi",
        token_usage=token_usage, round=1,
    )


def test_serialize_message_cost_from_token_usage():
    m = _msg({"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.5})
    out = serialize_message(m)
    assert out["cost"] == 0.5


def test_serialize_message_cost_zero_when_missing():
    # 无 cost 字段 → 0.0
    m = _msg({"prompt_tokens": 10})
    assert serialize_message(m)["cost"] == 0.0
    # token_usage 为 None → 0.0
    assert serialize_message(_msg(None))["cost"] == 0.0
