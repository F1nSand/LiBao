"""事件收件箱 + 规则裁决器（《02》后端设计 §5.3.1/§5.3.2 最小闭环）。

事件（后台任务回填、外部触发）只在**轮边界安全点**被消费——route 节点入口 drain，
绝不在工具执行中途插入（《02》后端设计 §5.3.1）。本轮最小闭环：`regular` 事件排空进 context
（模型下一轮可见）+ 匹配占位任务的 `job_done` 触发回填 tool_result；`urgent/light` 预留。

进程内收件箱（keyed by thread_key）：事件在后台任务完成时 emit，直到下一次 route drain 才取出，
因此跨用户消息的回填也能工作（下一轮 drain 时送达）。容量有上限防泄漏（单实例足够）。
"""

from __future__ import annotations

from typing import Any

EVENT_REGULAR = "regular"  # 常规：轮边界排空进 context（本轮实现）
EVENT_URGENT = "urgent"  # 预留：可打断当前轮（interrupt/cancel）
EVENT_LIGHT = "light"  # 预留：独立并行执行

# 进程内收件箱：thread_key → list[event]。drain 消费即清；emit 追加（有上限，防泄漏）。
_inbox: dict[str, list[dict[str, Any]]] = {}
_MAX_EVENTS_PER_THREAD = 100
_MAX_THREADS = 1024


def emit_event(thread_key: str, event: dict[str, Any]) -> None:
    """事件入队（后台任务回填等）。线程无 key / 收件箱满则丢弃（尽力而为）。"""
    if not thread_key:
        return
    events = _inbox.setdefault(thread_key, [])
    events.append(event)
    if len(events) > _MAX_EVENTS_PER_THREAD:
        del events[: len(events) - _MAX_EVENTS_PER_THREAD]
    if len(_inbox) > _MAX_THREADS:
        # 全局上限：淘汰最早一个线程（未消费的过期事件）
        _inbox.pop(next(iter(_inbox)))


def drain_events(thread_key: str) -> list[dict[str, Any]]:
    """安全点排空：取走该线程全部事件（消费即清，供 route 节点调用）。"""
    if not thread_key:
        return []
    return _inbox.pop(thread_key, [])


def arbitrate(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """规则裁决器（《02》后端设计 §5.3.2，默认规则起步）：按 priority 分类。
    - urgent：置顶进 context（紧急优先响应，M6 前补强）；
    - regular：排空进 context；
    - light：预留（独立并行执行，本轮不进 context）。
    """
    urgent = [e for e in events if (e.get("priority") or EVENT_REGULAR) == EVENT_URGENT]
    regular = [e for e in events if (e.get("priority") or EVENT_REGULAR) == EVENT_REGULAR]
    return {"urgent": urgent, "regular": regular}
