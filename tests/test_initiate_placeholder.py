"""M4 完整版：initiate_* 占位/回填最小闭环测试（docs 01 §5.5 + §5.3.1/5.3.2）。

覆盖：handler 占位契约 → executor 透出 placeholder/job_ref → route 安全点排空 →
job_done 命中占位任务发回填 tool_result；regular 事件渲染成系统备注。
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from app.orchestration.graph import build_graph
from app.orchestration.nodes.route import route_node
from app.services.events import arbitrate, drain_events, emit_event
from app.tools import executor
from app.tools.builtin import register_builtin_tools
from app.tools.builtin.initiate_demo import initiate_demo_handler
from app.tools.context import set_dispatch_ctx
from app.tools.registry import ToolSpec, register, unregister


async def test_handler_returns_placeholder_contract():
    set_dispatch_ctx({"thread_key": "thr-h", "push": lambda t, p: ""})
    try:
        out = await initiate_demo_handler(delay=1, note="计算完成")
        assert out["placeholder"] is True
        assert out["job_ref"].startswith("job_")
        assert "已发起后台任务" in out["summary"]
    finally:
        set_dispatch_ctx(None)


async def test_executor_propagates_placeholder_to_toolresult():
    spec = ToolSpec(
        id="tl_demo_init", name="demo_init", description="占位演示工具",
        handler=initiate_demo_handler, timeout_ms=5000,
    )
    register(spec)
    set_dispatch_ctx({"thread_key": "thr-e", "push": lambda t, p: ""})
    try:
        result = await executor.execute(spec, {"delay": 1, "note": "hi"})
        assert result.placeholder is True
        assert result.job_ref and result.job_ref.startswith("job_")
        assert "已发起后台任务" in result.summary
    finally:
        unregister(spec.id)
        set_dispatch_ctx(None)


async def test_route_node_backfills_matched_job():
    job_ref = "job_test1"
    state = {
        "flags": {"steps": 0},
        "placeholder_jobs": [
            {"job_ref": job_ref, "tool_call_id": "call_1", "tool_name": "demo_init", "created_at": "x"}
        ],
        "tool_results": [],
        "run_logs": [],
    }
    drain_events("thr-route")
    emit_event("thr-route", {"type": "job_done", "job_ref": job_ref, "result": {"note": "完成"}, "priority": "regular"})
    pushed: list[tuple[str, dict]] = []

    def push(t: str, p: dict) -> str:
        pushed.append((t, p))
        return ""

    set_dispatch_ctx({"thread_key": "thr-route", "push": push})
    try:
        out = await route_node(state, {"configurable": {"thread_id": "thr-route"}})
        # 回填 tool_result 帧（前端占位卡解析：placeholder:false + 同 job_ref）
        backfills = [p for t, p in pushed if t == "tool_result" and p["job_ref"] == job_ref]
        assert backfills and backfills[0]["placeholder"] is False
        assert backfills[0]["tool_call_id"] == "call_1" and backfills[0]["structured"] == {"note": "完成"}
        # 占位任务已移除
        assert all(p["job_ref"] != job_ref for p in out["placeholder_jobs"])
        # 已回填的 job_done 不进 context 备注
        assert out["messages"] == []
    finally:
        set_dispatch_ctx(None)


async def test_route_node_surfaces_regular_event_note():
    drain_events("thr-note")
    emit_event("thr-note", {"type": "ext_event", "result": {"note": "外部提示"}, "priority": "regular"})
    set_dispatch_ctx({"thread_key": "thr-note"})
    try:
        out = await route_node({"flags": {}, "placeholder_jobs": []}, {"configurable": {"thread_id": "thr-note"}})
        notes = [m for m in out["messages"] if m.type == "system"]
        assert notes and "外部提示" in notes[0].content
    finally:
        set_dispatch_ctx(None)


def test_arbitrate_filters_regular():
    events = [
        {"type": "a", "priority": "regular"},
        {"type": "b", "priority": "urgent"},  # 预留：不进 context
        {"type": "c", "priority": "light"},  # 预留
    ]
    assert [e["type"] for e in arbitrate(events)] == ["a"]


async def test_graph_run_registers_placeholder_job():
    """图级集成：模型调 initiate_demo → tool_execute 登记占位任务 → placeholder_jobs 累积。"""
    register_builtin_tools()

    class FakeChatModel:
        def __init__(self) -> None:
            self._n = 0

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            self._n += 1
            if self._n == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "initiate_demo",
                            "args": {"delay": 0, "note": "x"},
                            "id": "call_i",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(content="已发起后台任务。")

    graph = build_graph()
    set_dispatch_ctx({"thread_key": "thr-g", "push": lambda t, p: ""})
    try:
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content="发起后台任务")],
                "agent_config": {
                    "name": "通用助手",
                    "model": "fake",
                    "system_prompt": "你是助手。",
                    "tools": ["tl_initiate_demo"],
                    "max_steps": 5,
                    "org_id": "",
                },
            },
            {"configurable": {"model": FakeChatModel(), "thread_id": "thr-g"}},
        )
        jobs = result.get("placeholder_jobs") or []
        assert any(j["job_ref"].startswith("job_") and j["tool_name"] == "initiate_demo" for j in jobs)
    finally:
        set_dispatch_ctx(None)
        drain_events("thr-g")
