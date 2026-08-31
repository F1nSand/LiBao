from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.messages import AIMessageChunk

from app.core.errors import LLMTransportError
from app.core.events import sse_emitter
from app.orchestration.stream_core import stream_graph_events


class _FailingStreamGraph:
    async def astream(self, initial, config, stream_mode):
        yield ("messages", (AIMessageChunk(content="abc"), {"langgraph_node": "agent_execute"}))
        chunk = LLMTransportError(model="glm-5.3-flash")
        raise chunk


@pytest.mark.asyncio
async def test_stream_attempt_metrics_count_text_and_idle_time():
    frames = [
        frame
        async for frame in stream_graph_events(
            graph=_FailingStreamGraph(),
            initial={},
            graph_config={"configurable": {"thread_id": "metrics-thread"}},
            emit=sse_emitter(),
        )
    ]
    errors = [
        json.loads(frame.split("\n\n")[0].split("data: ", 1)[1])
        for frame in frames
        if frame.startswith("event: error")
    ]
    assert len(errors) == 1
    details = errors[0]["payload"]["details"]
    assert details["chunks_received"] == 1
    assert details["text_chars"] == 3
    assert details["elapsed_ms"] >= 0
    assert details["last_chunk_age_ms"] >= 0


@pytest.mark.asyncio
async def test_stream_attempt_metrics_ignore_non_agent_chunks():
    class Graph:
        async def astream(self, initial, config, stream_mode):
            yield ("messages", (AIMessageChunk(content="ignored"), {"langgraph_node": "tool_execute"}))
            raise LLMTransportError(model="fake")

    frames = [
        frame
        async for frame in stream_graph_events(
            graph=Graph(),
            initial={},
            graph_config={"configurable": {"thread_id": "metrics-thread-2"}},
            emit=sse_emitter(),
        )
    ]
    error = next(
        json.loads(frame.split("\n\n")[0].split("data: ", 1)[1])
        for frame in frames
        if frame.startswith("event: error")
    )
    assert error["payload"]["details"]["chunks_received"] == 0


@pytest.mark.asyncio
async def test_stream_model_progress_is_throttled_to_keepalive_interval():
    events: list[tuple[str, dict]] = []

    async def sink(kind: str, payload: dict) -> None:
        events.append((kind, payload))

    class SlowGraph:
        async def astream(self, initial, config, stream_mode):
            await asyncio.sleep(0.035)
            yield ("values", {})

    frames = [
        frame
        async for frame in stream_graph_events(
            graph=SlowGraph(),
            initial={},
            graph_config={"configurable": {"thread_id": "metrics-thread-3"}},
            emit=sse_emitter(),
            keepalive_interval=0.01,
            task_event_sink=sink,
        )
    ]
    assert frames
    assert 1 <= len(events) <= 4
    assert all(kind == "status" and payload["phase"] == "model_streaming" for kind, payload in events)


@pytest.mark.asyncio
async def test_stream_persists_business_boundary_events_without_tokens():
    events: list[tuple[str, dict]] = []

    async def sink(kind: str, payload: dict) -> None:
        events.append((kind, payload))

    class Graph:
        async def astream(self, initial, config, stream_mode):
            yield (
                "updates",
                {
                    "agent_execute": {
                        "messages": [
                            type(
                                "ToolMessage",
                                (),
                                {
                                    "tool_calls": [
                                        {"id": "call-1", "name": "shell", "args": {"command": "echo hi"}}
                                    ],
                                    "content": "",
                                    "usage_metadata": {},
                                    "additional_kwargs": {},
                                },
                            )()
                        ]
                    }
                },
            )
            yield (
                "updates",
                {
                    "tool_execute": {
                        "tool_results": [
                            {
                                "tool_call_id": "call-1",
                                "tool_name": "shell",
                                "ok": True,
                                "summary": "hi",
                                "output": {"stdout": "hi"},
                            }
                        ]
                    }
                },
            )
            yield ("values", {"final_message": {"content": "done"}})

    frames = [
        frame
        async for frame in stream_graph_events(
            graph=Graph(),
            initial={},
            graph_config={"configurable": {"thread_id": "events-thread"}},
            emit=sse_emitter(),
            task_event_sink=sink,
        )
    ]
    assert frames
    assert [kind for kind, _ in events] == ["tool_call", "tool_result", "message"]
    assert events[-1][1]["message"]["content"] == ""
    assert all("input" not in payload or payload["input"] for _, payload in events[:1])
