"""tl_initiate_demo 内置工具（docs 01 §5.5 工具级异步最小闭环）。

演示 initiate_* 占位/回填：立即返回占位（placeholder:true + job_ref），
后台延迟 N 秒后 emit `job_done` 事件 → 轮边界（route 节点）排空 → 匹配占位任务
回填 tool_result（placeholder:false）+ 事件备注进 context（模型下一轮可见）。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.services.events import emit_event
from app.tools.context import dispatch_thread_key


async def initiate_demo_handler(delay: int = 3, note: str = "") -> dict[str, Any]:
    """发起一个演示后台任务。返回占位契约（executor 透出 placeholder/job_ref）。"""
    job_ref = f"job_{uuid.uuid4().hex[:8]}"
    thread_key = dispatch_thread_key()
    summary = note or f"后台任务 {job_ref}"

    async def _run() -> None:
        await asyncio.sleep(max(0, delay))
        emit_event(
            thread_key,
            {
                "type": "job_done",
                "job_ref": job_ref,
                "result": {"note": summary, "ok": True},
                "priority": "regular",
            },
        )

    asyncio.create_task(_run())
    return {"placeholder": True, "job_ref": job_ref, "summary": f"已发起后台任务（{delay}s 后完成）：{summary}"}
