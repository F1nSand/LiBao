"""任务队列服务（M4）。服务层只触存储层（storage.redis），不碰编排。
Redis 不可用 → 入队返回 False，调用方（路由）降级进程内 create_task。
"""
from __future__ import annotations

import uuid

from app.storage.redis import enqueue_task


class TaskQueueService:
    @staticmethod
    async def enqueue_submit(task_id: uuid.UUID, trace_id: str) -> bool:
        """提交任务入队（worker 消费后跑 run_task_graph）。"""
        return await enqueue_task({"kind": "submit", "task_id": str(task_id), "trace_id": trace_id})

    @staticmethod
    async def enqueue_resume(task_id: uuid.UUID, approved: bool, trace_id: str) -> bool:
        """JSON 轨 resume 入队（worker 消费后跑 resume_task_graph）。"""
        return await enqueue_task(
            {"kind": "resume", "task_id": str(task_id), "approved": approved, "trace_id": trace_id}
        )
