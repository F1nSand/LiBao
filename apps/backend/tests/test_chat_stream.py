"""T10 SSE 桥测试：精确信封序列（message_start→tool_call→tool_result→token→status→done）+ 消息持久化。

需要 Docker db（localhost:5432）；DB 不可达时自动跳过（review gate 无 DB 也能跑其余测试）。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.core.errors import AppError
from app.orchestration.chat_stream import _graph_config, _resolve_previous_message_head, chat_stream_events
from app.orchestration.checkpointer import JsonFileSaver
from app.orchestration.graph import build_graph
from app.orchestration.task_worker import route_cancel, running_task
from app.services.task import TaskService
from app.services.task_events import list_task_events
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Conversation, User
from app.storage.repositories.conversation import ConversationRepository
from app.storage.repositories.message import MessageRepository
from app.storage.repositories.task import TaskRepository


class FakeChatModel:
    def __init__(self) -> None:
        self._n = 0

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        if self._n == 0:
            self._n = 1
            return AIMessage(
                content="", tool_calls=[{"name": "time_now", "args": {}, "id": "call_1", "type": "tool_call"}]
            )
        return AIMessage(content="现在是 2026 年 8 月 13 日 21:00。")


def test_graph_config_distinguishes_code_anchor_from_graph_parent():
    cfg = _graph_config(
        thread_id="conversation-1",
        trace_id="trace-1",
        assistant_msg_id=uuid.uuid4(),
        checkpoint_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        graph_parent_checkpoint_id="graph-before-1",
    )

    assert cfg["configurable"]["code_checkpoint_id"] == "11111111-1111-1111-1111-111111111111"
    assert cfg["configurable"]["checkpoint_id"] == "graph-before-1"
    assert "start_graph_from_root" not in cfg["configurable"]


def test_graph_config_accepts_explicit_code_checkpoint_id():
    code_checkpoint_id = uuid.uuid4()
    cfg = _graph_config(
        thread_id="conversation-1",
        trace_id="trace-1",
        assistant_msg_id=uuid.uuid4(),
        code_checkpoint_id=code_checkpoint_id,
        graph_parent_checkpoint_id="graph-before-1",
    )

    assert cfg["configurable"]["code_checkpoint_id"] == str(code_checkpoint_id)
    assert cfg["configurable"]["checkpoint_id"] == "graph-before-1"


@pytest.mark.asyncio
async def test_empty_message_cursor_does_not_resurrect_legacy_history():
    class _Messages:
        async def list_by_conversation(self, conversation_id, *, limit, offset):
            return [SimpleNamespace(id=uuid.uuid4())]

    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        active_message_head_id=None,
        message_cursor_initialized=True,
    )
    assert await _resolve_previous_message_head(conversation, _Messages()) is None


@pytest.mark.asyncio
async def test_legacy_message_cursor_uses_append_only_tail_as_parent():
    tail = uuid.uuid4()

    class _Messages:
        async def list_by_conversation(self, conversation_id, *, limit, offset):
            return [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=tail)]

    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        active_message_head_id=None,
        message_cursor_initialized=False,
    )
    assert await _resolve_previous_message_head(conversation, _Messages()) == tail


def test_graph_config_marks_explicit_empty_graph_root():
    cfg = _graph_config(
        thread_id="conversation-1",
        trace_id="trace-1",
        assistant_msg_id=uuid.uuid4(),
        checkpoint_id=uuid.uuid4(),
        start_graph_from_root=True,
    )

    assert cfg["configurable"]["start_graph_from_root"] is True
    assert "checkpoint_id" not in cfg["configurable"]


@pytest.fixture
async def chat_fixture():
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"t10_{uid}", password_hash="hashed", name="T10", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=uuid.UUID(int=0),
            name="T10时间助手",
            model="fake",
            system_prompt="你是时间助手。",
            tools=["tl_time_now"],
            max_steps=5,
            status="published",
        )
        session.add(agent)
        await session.flush()
        conv = Conversation(user_id=user.id, agent_id=agent.id, title="t10会话")
        session.add(conv)
        await session.commit()
    yield user, agent, conv


async def test_chat_stream_event_sequence(chat_fixture):
    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    user, agent, conv = chat_fixture
    graph = build_graph()

    async with get_store().session() as session:
        frames = []
        async for frame in chat_stream_events(
            db=session,
            graph=graph,
            conversation=conv,
            agent=agent,
            user=user,
            content="现在几点？",
            trace_id="trace-t10",
            model_override=FakeChatModel(),
        ):
            frames.append(frame)

        events = []
        for frame in frames:
            if frame.startswith(":"):  # keepalive 注释跳过
                continue
            data = frame.split("\n\n")[0].split("data: ", 1)[1]
            events.append(json.loads(data))

        types = [e["type"] for e in events]
        assert types[0] == "message_start"
        assert "tool_call" in types and "tool_result" in types and "token" in types
        assert "status" in types
        assert types[-1] == "done"
        seqs = [e["seq"] for e in events]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

        tool_call = next(e for e in events if e["type"] == "tool_call")
        assert tool_call["payload"]["tool_name"] == "time_now"
        tool_result = next(e for e in events if e["type"] == "tool_result")
        assert tool_result["payload"]["ok"] is True
        # 逐轮消息（《02》接口契约 §3）：第 1 轮（工具）发 message 事件；最终轮由 done 承载
        seal = next(e for e in events if e["type"] == "message")
        assert seal["payload"]["message"]["round"] == 1
        assert seal["payload"]["message"]["tool_calls"][0]["tool_name"] == "time_now"
        done = events[-1]
        assert done["payload"]["message"]["role"] == "assistant"
        assert done["payload"]["message"]["round"] == 2

        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        start_payload = events[0]["payload"]
        assert start_payload["user_message_id"] == str(msgs[0].id)
        assert start_payload["checkpoint_id"] == str(msgs[0].checkpoint_id)
        roles = [m.role for m in msgs]
        assert roles == ["user", "assistant", "assistant"]  # 工具轮 + 最终轮各一条
        assert msgs[0].content == "现在几点？"
        assert msgs[1].round == 1 and msgs[1].tool_calls and msgs[1].tool_calls[0]["tool_name"] == "time_now"
        assert msgs[2].round == 2 and msgs[2].tool_calls == []
        assert msgs[1].trace_id == "trace-t10"


async def test_chat_task_lifecycle_exposes_id_and_finishes_done(chat_fixture):
    """普通聊天复用同一 Task：首帧带 task_id，最终状态 done。"""
    user, agent, conv = chat_fixture
    task_service = TaskService()
    async with get_store().session() as session:
        task = await task_service.submit(session, user, agent.id, {"message": "hello"})
        await task_service.set_running(session, task)
        frames = []
        async for frame in chat_stream_events(
            db=session,
            graph=build_graph(),
            conversation=conv,
            agent=agent,
            user=user,
            content="hello",
            trace_id="trace-chat-task",
            task=task,
            model_override=SlowFakeModel(),
        ):
            frames.append(frame)
        events = [
            json.loads(frame.split("\n\n")[0].split("data: ", 1)[1])
            for frame in frames
            if not frame.startswith(":")
        ]
        assert events[0]["type"] == "message_start"
        assert events[0]["payload"]["task_id"] == str(task.id)
        assert events[0]["payload"]["user_message_id"]
        assert events[0]["payload"]["checkpoint_id"]
        stored_events = await list_task_events(str(task.id))
        persisted_start = next(item for item in stored_events if item["type"] == "message_start")
        assert persisted_start["payload"]["user_message_id"] == events[0]["payload"]["user_message_id"]
        assert persisted_start["payload"]["checkpoint_id"] == events[0]["payload"]["checkpoint_id"]
        assert events[-1]["type"] == "done"
        stored = await TaskRepository(session).get_by_id(task.id)
        assert stored.status == "done"


async def test_cancelled_chat_task_does_not_start_graph(chat_fixture):
    """首帧前已取消的聊天不应启动 graph 或发出 message_start。"""
    user, agent, conv = chat_fixture
    task_service = TaskService()
    async with get_store().session() as session:
        task = await task_service.submit(session, user, agent.id, {"message": "cancelled"})
        await task_service.set_running(session, task)
        await task_service.cancel(session, task)

        class ExplodingGraph:
            async def astream(self, *_args, **_kwargs):
                raise AssertionError("cancelled chat must not start graph")
                yield  # pragma: no cover

        frames = [
            frame
            async for frame in chat_stream_events(
                db=session,
                graph=ExplodingGraph(),
                conversation=conv,
                agent=agent,
                user=user,
                content="cancelled",
                trace_id="trace-chat-pre-cancel",
                task=task,
            )
        ]
        assert frames == []
        stored = await TaskRepository(session).get_by_id(task.id)
        assert stored.status == "cancelled"


async def test_running_chat_cancel_skips_final_message(chat_fixture):
    """运行中取消普通聊天：graph 被打断且不落库最终 assistant。"""
    user, agent, conv = chat_fixture
    task_service = TaskService()
    async with get_store().session() as session:
        task = await task_service.submit(session, user, agent.id, {"message": "slow"})
        await task_service.set_running(session, task)
        task_id = task.id

        async def consume() -> list[str]:
            return [
                frame
                async for frame in chat_stream_events(
                    db=session,
                    graph=build_graph(),
                    conversation=conv,
                    agent=agent,
                    user=user,
                    content="slow",
                    trace_id="trace-chat-cancel",
                    task=task,
                    model_override=SlowFakeModel(),
                )
            ]

        stream_job = asyncio.create_task(consume())
        for _ in range(100):
            if running_task(str(task_id)) is not None:
                break
            await asyncio.sleep(0.01)
        assert running_task(str(task_id)) is not None
        async with get_store().session() as cancel_session:
            current = await TaskRepository(cancel_session).get_by_id(task_id)
            await task_service.cancel(cancel_session, current)
        await route_cancel(str(task_id))
        await stream_job

        stored = await TaskRepository(session).get_by_id(task_id)
        assert stored.status == "cancelled"
        messages = await MessageRepository(session).list_by_conversation(conv.id)
        assert [message.role for message in messages] == ["user"]
        assert all("event: done" not in frame for frame in stream_job.result())


async def test_chat_finalization_wins_cancel_race(chat_fixture, monkeypatch):
    """最终落库持锁时取消等待；完成胜出后取消返回 40902。"""
    user, agent, conv = chat_fixture
    task_service = TaskService()
    entered = asyncio.Event()
    release = asyncio.Event()
    original_set_done = TaskService.set_done

    async def delayed_set_done(self, db, task, final_message, **kwargs):
        entered.set()
        await release.wait()
        return await original_set_done(self, db, task, final_message, **kwargs)

    monkeypatch.setattr(TaskService, "set_done", delayed_set_done)
    async with get_store().session() as session:
        task = await task_service.submit(session, user, agent.id, {"message": "race"})
        await task_service.set_running(session, task)

        async def consume() -> list[str]:
            return [
                frame
                async for frame in chat_stream_events(
                    db=session,
                    graph=build_graph(),
                    conversation=conv,
                    agent=agent,
                    user=user,
                    content="race",
                    trace_id="trace-chat-race",
                    task=task,
                    model_override=SlowFakeModel(),
                )
            ]

        stream_job = asyncio.create_task(consume())
        await asyncio.wait_for(entered.wait(), timeout=10)

        async def cancel() -> AppError | None:
            async with get_store().session() as cancel_session:
                current = await TaskRepository(cancel_session).get_by_id(task.id)
                try:
                    await task_service.cancel(cancel_session, current)
                except AppError as exc:
                    return exc
            return None

        cancel_job = asyncio.create_task(cancel())
        await asyncio.sleep(0)
        assert not cancel_job.done()
        release.set()
        frames = await stream_job
        cancel_error = await cancel_job
        assert cancel_error is not None and cancel_error.code == 40902
        assert any("event: done" in frame for frame in frames)
        stored = await TaskRepository(session).get_by_id(task.id)
        assert stored.status == "done"
        messages = await MessageRepository(session).list_by_conversation(conv.id)
        assert [message.role for message in messages] == ["user", "assistant"]


async def test_message_seal_carries_cost(chat_fixture):
    """逐轮 cost 表面化（M6-2）：message 封口事件与 done 消息均含 cost（Fake 无 usage → 0.0）。"""
    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    user, agent, conv = chat_fixture
    graph = build_graph()

    async with get_store().session() as session:
        frames = []
        async for frame in chat_stream_events(
            db=session, graph=graph, conversation=conv, agent=agent, user=user,
            content="现在几点？", trace_id="trace-t10-cost", model_override=FakeChatModel(),
        ):
            frames.append(frame)

        events = []
        for frame in frames:
            if frame.startswith(":"):
                continue
            events.append(json.loads(frame.split("\n\n")[0].split("data: ", 1)[1]))

        seal = next(e for e in events if e["type"] == "message")
        assert seal["payload"]["cost"] == 0.0
        assert seal["payload"]["message"]["cost"] == 0.0
        done = events[-1]
        assert done["payload"]["message"]["cost"] == 0.0


async def test_thinking_event_and_persistence(chat_fixture):
    """thinking（reasoning_content）：SSE 发射 + 按轮持久化（《02》接口契约 §3）。"""

    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    user, agent, conv = chat_fixture

    class ThinkingModel(FakeChatModel):
        async def ainvoke(self, messages):
            resp: AIMessage = await super().ainvoke(messages)
            resp.additional_kwargs["reasoning_content"] = "我在思考调用时间工具。"
            return resp

    graph = build_graph()
    async with get_store().session() as session:
        frames = []
        async for frame in chat_stream_events(
            db=session, graph=graph, conversation=conv, agent=agent, user=user,
            content="现在几点？", trace_id="trace-think", model_override=ThinkingModel(),
        ):
            frames.append(frame)

        events = []
        for frame in frames:
            if frame.startswith(":"):
                continue
            data = frame.split("\n\n")[0].split("data: ", 1)[1]
            events.append(json.loads(data))
        think_events = [e for e in events if e["type"] == "thinking"]
        assert think_events, "应发射 thinking 事件"
        assert think_events[0]["payload"]["text"] == "我在思考调用时间工具。"

        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        # 即时落库：任务完成后 DB 已有全部轮次
        assert [m.role for m in msgs] == ["user", "assistant", "assistant"]
        assert msgs[1].thinking == "我在思考调用时间工具。"  # 工具轮
        assert msgs[2].thinking == "我在思考调用时间工具。"  # 最终轮


async def test_default_title_updated_by_first_message(chat_fixture):
    """标题兜底：默认标题「新会话」在首条消息后自动用首句命名（前端新建按钮/API 创建的会话）。"""
    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    user, agent, conv = chat_fixture
    conv.title = "新会话"  # 模拟新建按钮/API 创建的默认标题
    graph = build_graph()

    async with get_store().session() as session:
        async for _ in chat_stream_events(
            db=session,
            graph=graph,
            conversation=conv,
            agent=agent,
            user=user,
            content="帮我写一个 Vue3 的计数器组件",
            trace_id="trace-title",
            model_override=FakeChatModel(),
        ):
            pass
        assert conv.title == "帮我写一个 Vue3 的计数器组件"


async def test_custom_title_not_overwritten(chat_fixture):
    """自定义标题（非「新会话」）不被首句覆盖。"""
    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    user, agent, conv = chat_fixture
    conv.title = "我的自定义标题"
    graph = build_graph()

    async with get_store().session() as session:
        async for _ in chat_stream_events(
            db=session,
            graph=graph,
            conversation=conv,
            agent=agent,
            user=user,
            content="第一条消息内容",
            trace_id="trace-title2",
            model_override=FakeChatModel(),
        ):
            pass
        assert conv.title == "我的自定义标题"


def test_title_from_truncate_semantics():
    """标题生成与前端 truncate 同语义：超长截断加省略号。"""
    from app.orchestration.chat_stream import _title_from

    assert _title_from("短标题") == "短标题"
    assert _title_from("这" * 25) == "这" * 20 + "…"
    assert _title_from("  空白  ") == "空白"


class SlowFakeModel:
    """带延迟的假模型：确保 aclose（模拟刷新断开）时 graph 仍在执行。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        await asyncio.sleep(0.5)
        return AIMessage(content="慢速回复完成")


class FailOnceModel:
    def __init__(self) -> None:
        self.calls = 0
        self.seen_human_messages: list[list[str]] = []

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.seen_human_messages.append([str(m.content) for m in messages if m.type == "human"])
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary model failure")
        return AIMessage(content="恢复成功")


async def test_chat_recovers_same_thread_after_model_error(chat_fixture, tmp_path):
    """首轮模型异常后，同一会话下一条消息从上一干净状态继续，失败输入不重放。"""
    user, agent, conv = chat_fixture
    model = FailOnceModel()
    graph = build_graph(JsonFileSaver(tmp_path / "chat-checkpoints"))

    async def run(content: str, trace_id: str) -> list[str]:
        frames: list[str] = []
        async with get_store().session() as session:
            async for frame in chat_stream_events(
                db=session,
                graph=graph,
                conversation=conv,
                agent=agent,
                user=user,
                content=content,
                trace_id=trace_id,
                model_override=model,
            ):
                frames.append(frame)
        return [
            json.loads(frame.split("\n\n")[0].split("data: ", 1)[1])["type"]
            for frame in frames
            if not frame.startswith(":")
        ]

    first_types = await run("失败消息", "trace-error-first")

    # The failed turn must leave a durable explicit empty graph cursor.  Reload
    # the file store to ensure recovery does not rely on the detached object.
    async with get_store().session() as session:
        await session.rollback()
        persisted = await ConversationRepository(session).table.get(conv.id)
    assert persisted is not None
    assert persisted.graph_cursor_initialized is True
    assert persisted.active_graph_checkpoint_id is None

    second_types = await run("恢复消息", "trace-error-second")

    assert first_types[-1] == "error"
    assert second_types[-1] == "done"
    assert "error" not in second_types
    assert model.seen_human_messages == [["失败消息"], ["恢复消息"]]
    async with get_store().session() as session:
        messages = await MessageRepository(session).list_by_conversation(conv.id)
    assert [message.role for message in messages] == ["user", "user", "assistant"]


async def test_disconnect_drains_and_finalizes(chat_fixture):
    """断线重连修复：客户端断开（生成器 aclose）→ graph 跑完 + on_final 正常落库。

    修复前：finally 直接 cancel producer → 最终 assistant 消息不落库 + checkpoint 停中间
    （刷新后会话残缺、重发重放旧轮）。修复后：排空队列让当前轮跑完再落库。
    """
    import asyncio

    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    user, agent, conv = chat_fixture
    graph = build_graph()

    async with get_store().session() as session:
        conv.title = "新会话"  # 默认标题：验证断流路径标题兜底同样生效
        agen = chat_stream_events(
            db=session,
            graph=graph,
            conversation=conv,
            agent=agent,
            user=user,
            content="慢速任务",
            trace_id="trace-drain",
            model_override=SlowFakeModel(),
        )
        await anext(agen)  # message_start（chat_stream_events 自身帧）
        await anext(agen)  # 进入 stream_graph_events 主循环（graph 已启动）后再断开
        await agen.aclose()  # 客户端断开（模拟刷新页面）
        # 等待后台收尾（drain 跑完 graph + on_final 落库）
        await asyncio.sleep(3)
        from app.storage.repositories.message import MessageRepository

        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        roles = [m.role for m in msgs]
        assert "assistant" in roles  # 最终消息已落库（修复前缺失）
        assert any("慢速回复完成" in (m.content or "") for m in msgs)
        # 会话标题也被首句更新（首条消息落库路径）
        assert conv.title == "慢速任务"

