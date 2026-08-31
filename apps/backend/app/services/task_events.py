"""任务级业务事件持久化与 live-tail 桥接。

事件 cursor 与单次 SSE 的 seq 分离：cursor 跨连接稳定，token/thinking 仍只在当前连接中传输。
"""

from __future__ import annotations

import asyncio
import copy
import time
import uuid
from typing import Any

from app.storage.file.store import get_store
from app.storage.repositories.task import TaskRepository

_EVENT_LOCKS: dict[str, asyncio.Lock] = {}
_SAFE_EVENT_TYPES = {
    "message_start",
    "model_retry",
    "status",
    "message",
    "tool_call",
    "tool_result",
    "agent_switch",
    "interrupt",
    "done",
    "error",
    "cancelled",
}
_FORBIDDEN_KEYS = {"api_key", "authorization", "prompt", "messages", "image_payload", "data_b64", "base64"}


def _lock(task_id: str) -> asyncio.Lock:
    return _EVENT_LOCKS.setdefault(task_id, asyncio.Lock())


def _clean(value: Any, *, key: str = "") -> Any:
    if key.lower() in _FORBIDDEN_KEYS:
        return None
    if isinstance(value, dict):
        return {k: cleaned for k, v in value.items() if (cleaned := _clean(v, key=str(k))) is not None}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, str):
        return value[:8000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:1000]


def project_task_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """生成可回放的安全投影；工具结果不持久化完整 output。"""

    projected = copy.deepcopy(payload)
    if event_type == "tool_result":
        projected.pop("output", None)
        projected.pop("input", None)
    elif event_type == "interrupt":
        interrupt_payload = projected.get("payload")
        if isinstance(interrupt_payload, dict):
            interrupt_payload.pop("input", None)
    elif event_type == "message":
        message = projected.get("message")
        if isinstance(message, dict):
            message.pop("thinking", None)
            for call in message.get("tool_calls", []) or []:
                if isinstance(call, dict):
                    call.pop("input", None)
                    call.pop("output", None)
    cleaned = _clean(projected)
    return cleaned if isinstance(cleaned, dict) else {}


async def _publish_with_store(task_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    async with store.session() as db:
        task = await TaskRepository(db).get_by_id(uuid.UUID(task_id))
        if task is None:
            return {"task_seq": 0, "type": event_type, "payload": {}}
        task.last_event_seq = int(getattr(task, "last_event_seq", 0) or 0) + 1
        record = {
            "task_seq": task.last_event_seq,
            "type": event_type,
            "ts": int(time.time() * 1000),
            "payload": project_task_payload(event_type, payload),
        }
        await store.jsonl_append(f"task_events/{task_id}.jsonl", record)
        await db.commit()
    return record


async def publish_task_event(task_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if event_type not in _SAFE_EVENT_TYPES:
        return None
    async with _lock(str(task_id)):
        record = await _publish_with_store(str(task_id), event_type, payload)
        queues = _TAILS.get(str(task_id), [])
        for queue in queues:
            queue.put_nowait((event_type, record["payload"], record["task_seq"]))
        if event_type in {"done", "error", "cancelled"}:
            for queue in queues:
                queue.put_nowait(None)
            _TAILS.pop(str(task_id), None)
        return record


async def list_task_events(task_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
    records = await get_store().jsonl_list(f"task_events/{task_id}.jsonl")
    return [r for r in records if int(r.get("task_seq", 0)) > after_seq]


_TAILS: dict[str, list[asyncio.Queue]] = {}


async def subscribe_task_events(task_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _TAILS.setdefault(str(task_id), []).append(queue)
    return queue


async def unsubscribe_task_events(task_id: str, queue: asyncio.Queue) -> None:
    queues = _TAILS.get(str(task_id), [])
    if queue in queues:
        queues.remove(queue)
    if not queues:
        _TAILS.pop(str(task_id), None)
