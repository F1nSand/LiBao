"""T6 流层中断测试（DB-backed）：chat 流 interrupt 落 Task + SSE 事件；resume 续流 done/cancelled。

需要 Docker db；DB 不可达自动跳过。
"""
from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import get_settings
from app.orchestration.chat_stream import chat_stream_events, resume_stream_events
from app.orchestration.graph import build_graph
from app.services.attachment import AttachmentService
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Conversation, User
from app.storage.repositories.message import MessageRepository
from app.storage.repositories.task import TaskRepository
from app.tools.registry import ToolSpec, register, unregister


class FakeChatModel:
    def __init__(self) -> None:
        self._n = 0
        self.seen: list[list] = []

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.seen.append([message.model_copy(deep=True) for message in messages])
        if self._n == 0:
            self._n = 1
            return AIMessage(
                content="",
                tool_calls=[{"name": "confirm_test", "args": {"msg": "hi"}, "id": "call_1", "type": "tool_call"}],
            )
        return AIMessage(content="已按确认结果处理。")


@pytest.fixture
async def interrupt_fixture():
    # 幂等：I6 后 register 拒同名遮蔽，进程内多次注册必须先摘除
    unregister("tl_confirm_test")
    register(
        ToolSpec(
            id="tl_confirm_test",
            name="confirm_test",
            description="需人工确认的演示工具",
            params_schema={"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
            require_confirm=True,
            enabled=True,
            handler=lambda msg: {"delivered": True, "msg": msg},
        )
    )
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"int_{uid}", password_hash="hashed", name="I", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=uuid.UUID(int=0),
            name="中断测试助手",
            model="fake",
            system_prompt="你是测试助手。",
            tools=["tl_confirm_test"],
            max_steps=5,
            status="published",
        )
        session.add(agent)
        await session.flush()
        conv = Conversation(user_id=user.id, agent_id=agent.id, title="中断会话")
        session.add(conv)
        await session.commit()
    yield user, agent, conv
    unregister("tl_confirm_test")  # 裸 _REGISTRY.pop 会残留 _NAME_INDEX（I6 后 name 遮蔽误伤）


def _frames_to_events(frames: list[str]) -> list[dict]:
    events = []
    for frame in frames:
        if frame.startswith(":"):
            continue
        data = frame.split("\n\n")[0].split("data: ", 1)[1]
        events.append(json.loads(data))
    return events


async def _run_interrupt(chat_fixture, graph, fake) -> tuple[list[dict], uuid.UUID]:
    """跑 chat_stream_events 到中断，返回 (events, task_id)。"""
    user, agent, conv = chat_fixture
    async with get_store().session() as session:
        frames = []
        async for frame in chat_stream_events(
            db=session,
            graph=graph,
            conversation=conv,
            agent=agent,
            user=user,
            content="发条消息",
            trace_id="trace-int",
            model_override=fake,
        ):
            frames.append(frame)
        events = _frames_to_events(frames)
        types = [e["type"] for e in events]
        assert "interrupt" in types
        assert "done" not in types
        interrupt = next(e for e in events if e["type"] == "interrupt")
        task_id = uuid.UUID(interrupt["payload"]["task_id"])
        # Task 行断言
        task = await TaskRepository(session).get_by_id(task_id)
        assert task is not None
        assert task.status == "waiting_confirm"
        assert task.pending_confirm["conversation_id"] == str(conv.id)
        return events, task_id


async def test_chat_interrupt_creates_task(interrupt_fixture):
    graph = build_graph()
    events, _ = await _run_interrupt(interrupt_fixture, graph, FakeChatModel())
    interrupt = next(e for e in events if e["type"] == "interrupt")
    assert interrupt["payload"]["node_id"] == "tool_execute"
    assert interrupt["payload"]["confirm_required"] is True
    assert interrupt["payload"]["task_id"]


async def test_resume_approved_done(interrupt_fixture):
    user, agent, conv = interrupt_fixture
    graph = build_graph(checkpointer=MemorySaver())  # resume 需 checkpointer 恢复中断点
    fake = FakeChatModel()
    _, task_id = await _run_interrupt(interrupt_fixture, graph, fake)

    async with get_store().session() as session:
        task = await TaskRepository(session).get_by_id(task_id)
        frames = []
        async for frame in resume_stream_events(
            db=session, graph=graph, task=task, user=user, approved=True, trace_id="trace-resume", model_override=fake
        ):
            frames.append(frame)
        events = _frames_to_events(frames)
        types = [e["type"] for e in events]
        assert "message_start" not in types  # 续流不得重置 segments
        assert "token" in types and "status" in types
        assert types[-1] == "done"
        done = events[-1]
        assert done["payload"]["message"]["tool_calls"] == []  # 最终轮无工具（逐轮消息，docs 03 §3）
        # 中断轮（confirm 工具）在 message 事件（resume 用工具结果重建轮，content 空）
        seal = next(e for e in events if e["type"] == "message")
        assert seal["payload"]["message"]["round"] == 1
        assert seal["payload"]["message"]["tool_calls"][0]["tool_name"] == "confirm_test"

        task2 = await TaskRepository(session).get_by_id(task_id)
        assert task2.status == "done"
        assert task2.output and task2.output.get("content") == "已按确认结果处理。"

        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        assert [m.role for m in msgs] == ["user", "assistant", "assistant"]  # 中断轮 + 最终轮
        assert msgs[1].round == 1 and msgs[1].tool_calls[0]["tool_name"] == "confirm_test"
        assert msgs[1].tool_calls[0]["status"] == "done"
        assert msgs[2].round == 2 and msgs[2].tool_calls == []


async def test_resume_denied_cancelled(interrupt_fixture):
    user, agent, conv = interrupt_fixture
    graph = build_graph(checkpointer=MemorySaver())  # resume 需 checkpointer 恢复中断点
    fake = FakeChatModel()
    _, task_id = await _run_interrupt(interrupt_fixture, graph, fake)

    async with get_store().session() as session:
        task = await TaskRepository(session).get_by_id(task_id)
        frames = []
        async for frame in resume_stream_events(
            db=session, graph=graph, task=task, user=user, approved=False, trace_id="trace-deny", model_override=fake
        ):
            frames.append(frame)
        events = _frames_to_events(frames)
        assert events[-1]["type"] == "done"
        assert events[-1]["payload"]["message"]["tool_calls"] == []  # 最终轮无工具（逐轮消息）
        # 拒绝分支：confirm 工具 cancelled 在该轮 message 事件（resume 用工具结果重建轮）
        seal = next(e for e in events if e["type"] == "message")
        assert seal["payload"]["message"]["round"] == 1
        assert seal["payload"]["message"]["tool_calls"][0]["status"] == "cancelled"

        task2 = await TaskRepository(session).get_by_id(task_id)
        assert task2.status == "cancelled"  # 拒绝分支任务保持 cancelled
        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        assert [m.role for m in msgs] == ["user", "assistant", "assistant"]
        assert msgs[1].round == 1 and msgs[1].tool_calls[0]["status"] == "cancelled"
        assert msgs[2].tool_calls == []


async def test_resume_does_not_read_or_replay_images(interrupt_fixture, monkeypatch):
    """中断恢复显式清空图片上下文：不重读文件，历史 ref 降级为文本。"""
    user, agent, conv = interrupt_fixture
    agent.model = "gpt-4o"
    monkeypatch.setattr(get_settings(), "llm_vision_declared", None)
    async with get_store().session() as session:
        att = await AttachmentService().save_upload(session, user, "resume.png", "image/png", b"resume-image")
        attachment_id = str(att.id)

    graph = build_graph(checkpointer=MemorySaver())
    fake = FakeChatModel()
    async with get_store().session() as session:
        frames = []
        async for frame in chat_stream_events(
            db=session,
            graph=graph,
            conversation=conv,
            agent=agent,
            user=user,
            content="中断后继续看图",
            attachments=[attachment_id],
            trace_id="trace-resume-image",
            model_override=fake,
        ):
            frames.append(frame)
        events = _frames_to_events(frames)
        task_id = uuid.UUID(next(e for e in events if e["type"] == "interrupt")["payload"]["task_id"])

    async def fail_read(_service, _attachment):
        raise AssertionError("resume must not re-read attachments")

    monkeypatch.setattr(AttachmentService, "read_file", fail_read)
    async with get_store().session() as session:
        task = await TaskRepository(session).get_by_id(task_id)
        frames = []
        async for frame in resume_stream_events(
            db=session,
            graph=graph,
            task=task,
            user=user,
            approved=True,
            trace_id="trace-resume-image-2",
            model_override=fake,
        ):
            frames.append(frame)
        events = _frames_to_events(frames)
    assert events[-1]["type"] == "done"
    resumed_human = next(message for message in fake.seen[1] if message.type == "human")
    assert all(block.get("type") != "image" for block in resumed_human.content)
    assert "图片已省略" in str(resumed_human.content)
