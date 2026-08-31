"""运行日志实体（《02》数据模型 §3.10）。全链路 append-only，trace_id 贯穿；M5 演进为 span 树。

type: llm / tool / retrieval / memory / node / custom；status: ok / error / retried。
"""

import uuid
from dataclasses import dataclass, field

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class RunLog(Row):
    trace_id: str
    session_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    node: str = ""
    type: str = "node"
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    token_usage: dict | None = None
    duration_ms: int = 0
    status: str = "ok"
