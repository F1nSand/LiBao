"""Redis 存储层（docs 05 §2.1 / M4）。命名与连接单一来源：任务队列 / 事件广播 / 幂等缓存。

单实例 MVP；多实例（队列 BRPOP 天然分发 + Pub/Sub 天然 fanout）由队列/广播语义保证。
redis 不可用（连接失败/未 init）→ get_redis() 返回 None，调用方降级（进程内回退）。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings

TASK_QUEUE_KEY = "task:queue"
TERMINAL_EVENTS = {"done", "error", "cancelled"}
_IDEM_TTL_S = 3600
TASK_OWNER_TTL_S = 86400  # task claim TTL：任务最长运行时间；worker 崩溃后自动过期，防 cancel 误路由

_redis: aioredis.Redis | None = None


def init_redis(settings: Any | None = None) -> aioredis.Redis:
    """建全局客户端（redis-py 8 async）。失败仅告警，返回的客户端由调用方降级。"""
    global _redis
    settings = settings or get_settings()
    _redis = aioredis.from_url(
        settings.redis_url, decode_responses=True, socket_connect_timeout=3, health_check_interval=30
    )
    return _redis


def get_redis() -> aioredis.Redis | None:
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


# ---- 命名 ----

def task_evt_channel(task_id: str) -> str:
    return f"task:evt:{task_id}"


def notif_channel(user_id: str) -> str:
    return f"notif:user:{user_id}"


def task_owner_key(task_id: str) -> str:
    return f"task:owner:{task_id}"


def worker_cancel_channel(instance_id: str) -> str:
    return f"worker:cancel:{instance_id}"


# ---- 任务队列（B1）----

async def enqueue_task(payload: dict) -> bool:
    """rpush 任务队列；redis 不可用 → False（调用方降级进程内 create_task）。"""
    if _redis is None:
        return False
    await _redis.rpush(TASK_QUEUE_KEY, json.dumps(payload))
    return True


async def brpop_task(timeout: float = 1.0) -> dict | None:
    """brpop 队首任务；超时返回 None（worker 轮询 stop_event 优雅退出）。"""
    if _redis is None:
        return None
    item = await _redis.brpop(TASK_QUEUE_KEY, timeout=timeout)
    if item is None:
        return None
    _key, raw = item
    return json.loads(raw)


# ---- 任务归属 claim（M6-3：多实例 cancel 路由）----

async def claim_task(task_id: str, instance_id: str) -> None:
    """worker 消费任务后 claim 归属；TTL 防崩溃残留（SET key value EX ttl）。Redis 不可用 → no-op。"""
    if _redis is None:
        return
    await _redis.set(task_owner_key(task_id), instance_id, ex=TASK_OWNER_TTL_S)


async def release_task_claim(task_id: str) -> None:
    """任务结束/取消清除 claim。Redis 不可用 → no-op。"""
    if _redis is None:
        return
    await _redis.delete(task_owner_key(task_id))


async def get_task_owner(task_id: str) -> str | None:
    """查任务归属实例（cancel 路由）；无/Redis 不可用 → None。"""
    if _redis is None:
        return None
    return await _redis.get(task_owner_key(task_id))


async def publish_cancel(instance_id: str, task_id: str) -> None:
    """向持有实例广播 cancel 信号（PUBLISH worker:cancel:{instance_id}）。Redis 不可用 → no-op。"""
    if _redis is None:
        return
    await _redis.publish(worker_cancel_channel(instance_id), json.dumps({"task_id": task_id}))


# ---- 事件广播桥（B2，task/notification 复用）----

async def pubsub_bridge(pubsub: Any, channel: str, q: Any, terminal: bool = True) -> None:
    """监听 channel → 投递 (type, payload) 到 queue；terminal 时收到 __end__ 哨兵收尾。断线重连。"""
    while True:
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = json.loads(msg["data"])
                if terminal and data.get("type") == "__end__":
                    q.put_nowait(None)
                    return
                q.put_nowait((data["type"], data.get("payload")))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  断线重连
            import logging

            logging.getLogger(__name__).warning("redis pubsub bridge reconnect: %s", exc)
            await asyncio.sleep(1)
            with contextlib.suppress(Exception):
                await pubsub.subscribe(channel)


# ---- 幂等缓存（B3）----

async def idem_get(key: str) -> str | None:
    if _redis is None:
        return None
    return await _redis.get(f"idem:{key}")


async def idem_set(key: str, value: str, ttl: int = _IDEM_TTL_S) -> None:
    if _redis is None:
        return
    await _redis.set(f"idem:{key}", value, ex=ttl)
