"""任务后台运行器（docs 01 §5.3）。POST /tasks 提交 → 独立 session 跑图（thread_id = task.id）。

M2 最小实现：asyncio.create_task 后台执行（完整任务队列为 M4）。
中断时任务自身转 waiting_confirm（pending_confirm 落自身行）；resume 走 Command(resume)。
状态迁移前 re-read 行：运行中被取消不覆盖（兜底）。
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.orchestration.stream_core import stream_graph_events
from app.services.task import TaskService, push_event
from app.storage.repositories.agent import AgentRepository
from app.storage.repositories.task import TaskRepository

logger = logging.getLogger(__name__)


def _task_agent_state(agent: Any, input_text: str) -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content=input_text)],
        "agent_config": {
            "model": agent.model,
            "system_prompt": agent.system_prompt,
            "tools": agent.tools or [],
            "max_steps": agent.max_steps,
        },
        "flags": {"steps": 0},
        "tool_results": [],
        "run_logs": [],
    }


def _noop_emit(event_type: str, payload: dict[str, Any]) -> str:
    return ""


async def _run_graph_common(
    *, graph, sessionmaker, task_id: uuid.UUID, initial: Any, trace_id: str, model_override: Any = None
) -> None:
    """共享执行体：跑图 + 中断落自身行 + 终态迁移 + live-tail 事件。"""
    async with sessionmaker() as db:
        repo = TaskRepository(db)
        task = await repo.get_by_id(task_id)
        if task is None:
            return
        svc = TaskService()
        graph_config: dict[str, Any] = {"configurable": {"thread_id": str(task.id), "trace_id": trace_id}}
        if model_override is not None:
            graph_config["configurable"]["model"] = model_override

        async def on_interrupt(value: dict[str, Any]) -> None:
            updated = await repo.get_by_id(task_id)
            if updated is None:
                return None
            payload = dict(value)
            payload["thread_id"] = str(task.id)
            payload["conversation_id"] = None
            payload["created_at"] = datetime.now(UTC).isoformat()
            await TaskRepository(db).set_pending_confirm(updated, payload)
            await db.commit()
            push_event(
                str(task_id),
                "interrupt",
                {
                    "node_id": value.get("node_id"),
                    "payload": payload,
                    "confirm_required": True,
                    "task_id": str(task_id),
                },
            )
            return None

        async def on_final(final_state: dict[str, Any]) -> None:
            updated = await repo.get_by_id(task_id)
            if updated is None:
                return None
            # 落 run_logs（task 无会话，session_id 留空）
            from app.storage.repositories.run_log import RunLogRepository

            for log in final_state.get("run_logs", []):
                await RunLogRepository(db).create(task_id=task_id, **log)
            if updated.status != "cancelled":  # 运行中被取消不覆盖
                fm = final_state.get("final_message", {}) or {}
                await svc.set_done(db, updated, final_message=fm)
                push_event(
                    str(task_id),
                    "done",
                    {
                        "message_id": None,
                        "token_usage": final_state.get("totals") or {},
                        "cost": None,
                        "message": fm,
                    },
                )
            return None

        async def on_error(exc: Exception) -> None:
            # 图级异常（LLM 失败等）：任务置 failed（stream_core 已发 error 帧）
            updated = await repo.get_by_id(task_id)
            if updated is None:
                return None
            if updated.status == "running":
                await svc.set_failed(db, updated, str(exc))
                push_event(str(task_id), "error", {"code": 60001, "message": str(exc), "retryable": True})
            return None

        async for _ in stream_graph_events(
            graph=graph,
            initial=initial,
            graph_config=graph_config,
            emit=_noop_emit,
            on_interrupt=on_interrupt,
            on_final=on_final,
            on_error=on_error,
        ):
            pass


async def run_task_graph(
    *, graph: Any, sessionmaker: Any, task_id: uuid.UUID, trace_id: str, model_override: Any = None
) -> None:
    """POST /tasks 提交后的后台执行。"""
    try:
        async with sessionmaker() as db:
            task = await TaskRepository(db).get_by_id(task_id)
            if task is None:
                return
            agent = await AgentRepository(db).get_published(task.agent_id)
            if agent is None:
                await TaskService().set_failed(db, task, "Agent 不存在或未发布")
                push_event(
                    str(task_id),
                    "error",
                    {"code": 40404, "message": "Agent 不存在或未发布", "retryable": False},
                )
                return
            await TaskService().set_running(db, task)
        await _run_graph_common(
            graph=graph,
            sessionmaker=sessionmaker,
            task_id=task_id,
            initial=_task_agent_state(agent, str(task.input or {})),
            trace_id=trace_id,
            model_override=model_override,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("task %s failed", task_id)
        async with sessionmaker() as db:
            task = await TaskRepository(db).get_by_id(task_id)
            if task is not None:
                await TaskService().set_failed(db, task, str(exc))
                push_event(str(task_id), "error", {"code": 50001, "message": str(exc), "retryable": True})


async def resume_task_graph(
    *, graph: Any, sessionmaker: Any, task_id: uuid.UUID, approved: bool, trace_id: str, model_override: Any = None
) -> None:
    """任务 JSON 轨 resume：approved → 后台续跑图；denied → 直接置 cancelled。"""
    try:
        async with sessionmaker() as db:
            task = await TaskRepository(db).get_by_id(task_id)
            if task is None:
                return
            if not approved:
                await TaskService().set_cancelled(db, task)
                push_event(str(task_id), "cancelled", {"status": "cancelled"})
                return
            await TaskService().set_running(db, task)
        await _run_graph_common(
            graph=graph,
            sessionmaker=sessionmaker,
            task_id=task_id,
            initial=Command(resume={"approved": True}),
            trace_id=trace_id,
            model_override=model_override,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("resume task %s failed", task_id)
        async with sessionmaker() as db:
            task = await TaskRepository(db).get_by_id(task_id)
            if task is not None:
                await TaskService().set_failed(db, task, str(exc))
                push_event(str(task_id), "error", {"code": 50001, "message": str(exc), "retryable": True})
