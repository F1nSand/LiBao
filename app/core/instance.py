"""进程级实例标识（M6-3 多实例任务亲和）。

每个 backend/worker 进程一个唯一 instance_id（uuid4），供 task claim 归属与跨实例 cancel 路由。
惰性生成 + 进程级单例（非 env，重启即变——claim 带 TTL，旧 id 自动过期不会误路由）。
"""
from __future__ import annotations

import uuid

_instance_id: str | None = None


def get_instance_id() -> str:
    """取本进程实例 id（首次调用时 uuid4 生成，之后恒同）。"""
    global _instance_id
    if _instance_id is None:
        _instance_id = uuid.uuid4().hex
    return _instance_id
