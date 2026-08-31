from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessageChunk

from app.core.errors import LLMTransportError
from app.core.events import sse_emitter
from app.orchestration.stream_core import stream_graph_events


class _FailedCheckpoint:
    async def aget_failed_config(self, config):
        return {"configurable": {**config["configurable"], "checkpoint_id": "failed-agent-input"}}


class _RetryGraph:
    def __init__(self):
        self.checkpointer = _FailedCheckpoint()
        self.calls = []

    async def astream(self, initial, config, stream_mode):
        self.calls.append((initial, config))
        if len(self.calls) == 1:
            yield ("messages", (AIMessageChunk(content="partial"), {"langgraph_node": "agent_execute"}))
            raise LLMTransportError(model="glm-5.3-flash")
        yield ("messages", (AIMessageChunk(content="complete"), {"langgraph_node": "agent_execute"}))
        yield ("values", {"final_message": {"content": "complete"}})


@pytest.mark.asyncio
async def test_transport_failure_auto_retries_once_from_explicit_failed_checkpoint():
    graph = _RetryGraph()

    async def on_final(state):
        return {"message": state["final_message"]}

    frames = [
        frame
        async for frame in stream_graph_events(
            graph=graph,
            initial={"messages": []},
            graph_config={"configurable": {"thread_id": "retry-thread"}},
            emit=sse_emitter(),
            on_final=on_final,
        )
    ]
    events = [
        json.loads(frame.split("\n\n")[0].split("data: ", 1)[1])
        for frame in frames
        if not frame.startswith(":")
    ]
    assert [initial for initial, _ in graph.calls] == [{"messages": []}, None]
    assert graph.calls[1][1]["configurable"]["checkpoint_id"] == "failed-agent-input"
    assert [event["type"] for event in events] == ["token", "model_retry", "token", "done"]
    assert events[1]["payload"]["reset_partial"] is True


@pytest.mark.asyncio
async def test_second_transport_failure_is_reported_without_infinite_retry():
    class AlwaysFail(_RetryGraph):
        async def astream(self, initial, config, stream_mode):
            self.calls.append((initial, config))
            raise LLMTransportError(model="glm-5.3-flash")
            yield  # pragma: no cover

    graph = AlwaysFail()
    frames = [
        frame
        async for frame in stream_graph_events(
            graph=graph,
            initial={},
            graph_config={"configurable": {"thread_id": "retry-thread-2"}},
            emit=sse_emitter(),
        )
    ]
    errors = [
        json.loads(frame.split("\n\n")[0].split("data: ", 1)[1])
        for frame in frames
        if frame.startswith("event: error")
    ]
    assert len(graph.calls) == 2
    assert errors[0]["payload"]["code"] == 60008


@pytest.mark.asyncio
async def test_manual_recovery_initial_none_selects_failed_checkpoint_before_graph_run():
    graph = _RetryGraph()
    frames = [
        frame
        async for frame in stream_graph_events(
            graph=graph,
            initial=None,
            graph_config={"configurable": {"thread_id": "manual-recovery"}},
            emit=sse_emitter(),
        )
    ]
    assert frames
    assert graph.calls[0][0] is None
    assert graph.calls[0][1]["configurable"]["checkpoint_id"] == "failed-agent-input"


@pytest.mark.asyncio
async def test_manual_recovery_preserves_explicit_cursor_without_thread_fallback():
    class Checkpointer:
        def __init__(self):
            self.failed_config_calls = 0

        async def aget_failed_config(self, config):
            self.failed_config_calls += 1
            return {"configurable": {**config["configurable"], "checkpoint_id": "wrong-thread-error"}}

    class Graph:
        def __init__(self):
            self.checkpointer = Checkpointer()
            self.calls = []

        async def astream(self, initial, config, stream_mode):
            self.calls.append((initial, config))
            yield ("values", {"final_message": {"content": "continued"}})

    graph = Graph()

    async def on_final(state):
        return {"message": state["final_message"]}

    frames = [
        frame
        async for frame in stream_graph_events(
            graph=graph,
            initial=None,
            graph_config={"configurable": {"thread_id": "restart-thread", "checkpoint_id": "verified-cursor"}},
            emit=sse_emitter(),
            on_final=on_final,
        )
    ]

    assert frames
    assert graph.checkpointer.failed_config_calls == 0
    assert graph.calls[0][1]["configurable"]["checkpoint_id"] == "verified-cursor"
