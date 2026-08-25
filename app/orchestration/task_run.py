"""任务后台运行器（docs 01 §5.3）。POST /tasks 提交 → 独立 session 跑图（thread_id = task.id）。

M2 最小实现：asyncio.create_task 后台执行（完整任务队列为 M4）。
中断时任务自身转 waiting_confirm（pending_confirm 落自身行）；resume 走 Command(resume)。
状态迁移前 re-read 行：运行中被取消不覆盖（兜底）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command

from app.orchestration.stream_core import build_initial_state, stream_graph_events
from app.services.notification import maybe_notify_from_tool_results
from app.services.task import TaskService, push_event
from app.services.tool import ToolService
from app.storage.file.store import get_store
from app.storage.repositories.agent import AgentRepository
from app.storage.repositories.task import TaskRepository

logger = logging.getLogger(__name__)


def _task_input_text(input: Any) -> str:
    """任务输入 → LLM 可见文本（F11）：dict 优先取 message 字段，避免传 Python repr。"""
    if isinstance(input, dict):
        msg = input.get("message")
        if isinstance(msg, str):
            return msg
        return str(input)
    return str(input or {})


async def _extract_memory_after_task(
    final_state: dict[str, Any], user_id: Any, trace_id: str, task_id: uuid.UUID
) -> None:
    """任务完成后台主动记忆提取（无工作区 → 只落全局；best-effort 静默）。"""
    from app.services.memory_extract import extract_and_store

    await extract_and_store(
        messages=final_state.get("messages", []),
        user_id=str(user_id),
        trace_id=trace_id,
        task_id=task_id,
    )


async def _run_graph_common(
    *, graph, sessionmaker, task_id: uuid.UUID, initial: Any, trace_id: str, model_override: Any = None
) -> None:
    """共享执行体：跑图 + 中断落自身行 + 终态迁移 + live-tail 事件。"""
    async with get_store().session(sessionmaker) as db:
        repo = TaskRepository(db)
        task = await repo.get_by_id(task_id)
        if task is None:
            return
        svc = TaskService()
        # F1：中断任务（chat/invoke 来源）的 thread 在 pending_confirm 里（conversation.id / uuid4），
        # 不能硬编码 task.id——否则 JSON 轨 resume 打到无 checkpoint 的线程报 EmptyInputError
        thread_id = TaskService.resolve_resume_thread(task)
        graph_config: dict[str, Any] = {"configurable": {"thread_id": thread_id, "trace_id": trace_id}}
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
            await push_event(
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
            # M6 前：占位任务写端（docs 04 §3.3 F5）——任务结束时把在途占位状态落 task.placeholder_events
            placeholder_events = final_state.get("placeholder_jobs", [])
            if placeholder_events:
                updated.placeholder_events = placeholder_events
            if updated.status != "cancelled":  # 运行中被取消不覆盖
                fm = final_state.get("final_message", {}) or {}
                await svc.set_done(db, updated, final_message=fm)
                # 2d：demo_notify 确认执行后落通知（工具结果产生源）
                if updated.user_id is not None:
                    await maybe_notify_from_tool_results(db, updated.user_id, final_state)
                # 主动记忆：任务完成后台提取（无工作区 → 只落全局）
                if updated.user_id is not None:
                    from app.services.memory_extract import spawn_extract

                    spawn_extract(
                        _extract_memory_after_task(final_state, updated.user_id, trace_id, task_id)
                    )
                await push_event(
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
                await push_event(str(task_id), "error", {"code": 60001, "message": str(exc), "retryable": True})
            return None

        def task_emit(event_type: str, payload: dict[str, Any]) -> str:
            """任务路径 emit：无 SSE 客户端；agent_switch 转发进任务事件（TaskDetail 回放 subagent 切换），
            其余事件（token/tool_call 等）丢弃。转发用 create_task 不阻塞图执行（best-effort）。"""
            if event_type == "agent_switch":
                asyncio.create_task(push_event(str(task_id), "agent_switch", payload))
            return ""

        async for _ in stream_graph_events(
            graph=graph,
            initial=initial,
            graph_config=graph_config,
            emit=task_emit,
            on_interrupt=on_interrupt,
            on_final=on_final,
            on_error=on_error,
        ):
            pass


async def _mark_failed(sessionmaker: Any, task_id: uuid.UUID, exc: Exception, log_msg: str) -> None:
    """后台任务异常兜底：置 failed + 推 error（Simpl：收敛 run/resume 两处重复）。"""
    logger.exception(log_msg, task_id)
    async with get_store().session(sessionmaker) as db:
        task = await TaskRepository(db).get_by_id(task_id)
        if task is not None:
            await TaskService().set_failed(db, task, str(exc))
            await push_event(str(task_id), "error", {"code": 50001, "message": str(exc), "retryable": True})


async def run_task_graph(
    *, graph: Any, sessionmaker: Any, task_id: uuid.UUID, trace_id: str, model_override: Any = None
) -> None:
    """POST /tasks 提交后的后台执行。"""
    try:
        async with get_store().session(sessionmaker) as db:
            task = await TaskRepository(db).get_by_id(task_id)
            if task is None:
                return
            # F4：提交与 runner 启动之间可能被取消 → 非 pending 直接放弃（不翻回 running）
            if task.status != "pending":
                return
            agent = await AgentRepository(db).get_by_id(task.agent_id)
            if agent is None:
                await TaskService().set_failed(db, task, "Agent 不存在或未发布")
                await push_event(
                    str(task_id),
                    "error",
                    {"code": 40404, "message": "Agent 不存在或未发布", "retryable": False},
                )
                return
            await TaskService().set_running(db, task)
            user_id = str(task.user_id) if task.user_id else None
            enabled_tool_ids = await ToolService().enabled_tool_ids(db, agent.org_id)
        await _run_graph_common(
            graph=graph,
            sessionmaker=sessionmaker,
            task_id=task_id,
            initial=build_initial_state(
                agent,
                _task_input_text(task.input),
                user_id=user_id,
                enabled_tool_ids=enabled_tool_ids,
            ),
            trace_id=trace_id,
            model_override=model_override,
        )
    except Exception as exc:  # noqa: BLE001
        await _mark_failed(sessionmaker, task_id, exc, "task %s failed")


async def resume_task_graph(
    *, graph: Any, sessionmaker: Any, task_id: uuid.UUID, approved: bool, trace_id: str, model_override: Any = None
) -> None:
    """任务 JSON 轨 resume：approved → 后台续跑图；denied → 直接置 cancelled。"""
    try:
        async with get_store().session(sessionmaker) as db:
            task = await TaskRepository(db).get_by_id(task_id)
            if task is None:
                return
            if not approved:
                await TaskService().set_cancelled(db, task)
                await push_event(str(task_id), "cancelled", {"status": "cancelled"})
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
        await _mark_failed(sessionmaker, task_id, exc, "resume task %s failed")
