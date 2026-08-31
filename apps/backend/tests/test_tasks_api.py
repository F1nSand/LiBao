"""T7 任务服务/运行器测试（DB-backed）：submit→run→done、cancel 40902、resume 前置校验、events 回放。

需要 Docker db；DB 不可达自动跳过。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.api.main import create_app
from app.api.routers.tasks import _task_event_stream
from app.api.schemas.chat import CONTENT_LIMIT
from app.api.schemas.tasks import SubmitTaskRequest
from app.core.config import get_settings
from app.core.errors import AppError
from app.orchestration.checkpointer import JsonFileSaver
from app.orchestration.graph import build_graph
from app.orchestration.task_run import run_task_graph
from app.services.attachment import AttachmentService
from app.services.serializers import serialize_active_task
from app.services.task import TaskService
from app.storage.constants import ADMIN_USER, DEFAULT_ORG_ID
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Attachment, User
from app.storage.models.task import Task
from app.storage.repositories.run_log import RunLogRepository
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
        return AIMessage(content="任务执行完成。")


class CapturingTaskModel:
    def __init__(self, content: str = "任务图片处理完成。") -> None:
        self.content = content
        self.seen: list[list] = []

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.seen.append([message.model_copy(deep=True) for message in messages])
        return AIMessage(content=self.content)


@pytest.fixture
async def tasks_fixture():
    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"tasks_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=uuid.UUID(int=0),
            name="任务测试助手",
            model="fake",
            system_prompt="你是测试助手。",
            tools=["tl_time_now"],
            max_steps=5,
            status="published",
        )
        session.add(agent)
        await session.commit()
    yield user, agent


async def test_submit_and_run_to_done(tasks_fixture):
    user, agent = tasks_fixture
    graph = build_graph()
    async with get_store().session() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "现在几点？"})
        task_id = task.id
        assert task.status == "pending"

    await run_task_graph(
        graph=graph, task_id=task_id, trace_id="trace-t", model_override=FakeChatModel()
    )

    async with get_store().session() as session:
        task2 = await TaskRepository(session).get_by_id(task_id)
        assert task2.status == "done"
        assert task2.output and task2.output.get("content") == "任务执行完成。"
        n = len(await RunLogRepository().list_by_trace_id("trace-t"))
        assert n > 0  # run_logs 带 trace_id（文件化后按 trace_id 扫描）


async def _submit_task_with_image(tasks_fixture, content: str = "描述任务图片"):
    user, agent = tasks_fixture
    async with get_store().session() as session:
        attachment = await AttachmentService().save_upload(
            session, user, "task.png", "image/png", b"task-image-" + uuid.uuid4().bytes
        )
        task = await TaskService().submit(
            session, user, agent.id, {"message": content, "attachment_ids": [str(attachment.id)]}
        )
        return user, agent, task.id, str(attachment.id), attachment.storage_path


async def test_task_vision_hydrates_image_and_checkpoint_contains_no_base64(tasks_fixture, tmp_path, monkeypatch):
    user, agent, task_id, attachment_id, _ = await _submit_task_with_image(tasks_fixture)
    agent.model = "gpt-4o"
    monkeypatch.setattr(get_settings(), "llm_vision_declared", None)
    model = CapturingTaskModel()
    checkpoint_root = tmp_path / "checkpoints"
    await run_task_graph(
        graph=build_graph(checkpointer=JsonFileSaver(checkpoint_root)),
        task_id=task_id,
        trace_id="trace-task-vision",
        model_override=model,
    )

    human = next(message for message in model.seen[0] if message.type == "human")
    image = next(block for block in human.content if block.get("type") == "image")
    assert image["source_type"] == "base64" and image["mime_type"] == "image/png"
    sentinel = image["data"]
    async with get_store().session() as session:
        task = await TaskRepository(session).get_by_id(task_id)
        assert task.status == "done"
        assert sentinel not in task.to_dict().__repr__()
    assert all(sentinel not in path.read_text(encoding="utf-8") for path in checkpoint_root.glob("*.json"))
    assert attachment_id in task.input["attachment_ids"]


async def test_task_unknown_capability_reads_attachment(tasks_fixture, monkeypatch):
    user, agent, task_id, _, _ = await _submit_task_with_image(tasks_fixture)
    agent.model = "deepseek-chat"
    monkeypatch.setattr(get_settings(), "llm_vision_declared", None)
    model = CapturingTaskModel()
    await run_task_graph(graph=build_graph(), task_id=task_id, trace_id="trace-task-text", model_override=model)
    human = next(message for message in model.seen[0] if message.type == "human")
    assert isinstance(human.content, list)
    assert any(block.get("type") == "image" for block in human.content)


async def test_task_missing_file_degrades_and_completes(tasks_fixture, monkeypatch):
    user, agent, task_id, _, _ = await _submit_task_with_image(tasks_fixture)
    agent.model = "gpt-4o"
    monkeypatch.setattr(get_settings(), "llm_vision_declared", None)

    async def fail_read(_service, _attachment):
        raise OSError("file removed after submit")

    monkeypatch.setattr(AttachmentService, "read_file", fail_read)
    model = CapturingTaskModel()
    await run_task_graph(graph=build_graph(), task_id=task_id, trace_id="trace-task-missing", model_override=model)
    human = next(message for message in model.seen[0] if message.type == "human")
    assert isinstance(human.content, str)
    assert "1 张图片未能送达" in human.content
    async with get_store().session() as session:
        task = await TaskRepository(session).get_by_id(task_id)
        assert task.status == "done"


async def test_task_image_budget_keeps_order_and_reports_omitted_count(tasks_fixture, monkeypatch):
    user, agent = tasks_fixture
    agent.model = "gpt-4o"
    monkeypatch.setattr(get_settings(), "llm_vision_declared", None)
    monkeypatch.setattr(get_settings(), "image_total_budget_mb", 1)
    async with get_store().session() as session:
        first = await AttachmentService().save_upload(session, user, "first.png", "image/png", b"first")
        second = await AttachmentService().save_upload(
            session, user, "second.png", "image/png", b"second" * (400 * 1024)
        )
        task = await TaskService().submit(
            session,
            user,
            agent.id,
            {"message": "按顺序处理", "attachment_ids": [str(first.id), str(second.id)]},
        )
    model = CapturingTaskModel()
    await run_task_graph(graph=build_graph(), task_id=task.id, trace_id="trace-task-budget", model_override=model)
    human = next(message for message in model.seen[0] if message.type == "human")
    assert [block["data"] for block in human.content if block.get("type") == "image"]
    text = next(block["text"] for block in human.content if block.get("type") == "text")
    assert "1 张图片未能送达" in text


async def test_cancel_done_returns_40902(tasks_fixture):
    user, agent = tasks_fixture
    async with get_store().session() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        await TaskService().set_done(session, task, {"content": "ok"})
        with pytest.raises(AppError) as exc:
            await TaskService().cancel(session, task)
        assert exc.value.code == 40902


async def test_resume_precheck_rejects_cancelled(tasks_fixture):
    user, agent = tasks_fixture
    async with get_store().session() as session:
        task = await TaskService().create_waiting_confirm(
            session,
            user=user,
            agent_id=agent.id,
            input={},
            value={"node_id": "tool_execute"},
            thread_id=str(uuid.uuid4()),
        )
        await TaskService().set_cancelled(session, task)
        with pytest.raises(AppError) as exc:
            await TaskService().resume_precheck(session, task)
        assert exc.value.code == 40902


async def test_resume_precheck_rejects_expired_ttl(tasks_fixture):
    user, agent = tasks_fixture
    async with get_store().session() as session:
        task = await TaskService().create_waiting_confirm(
            session,
            user=user,
            agent_id=agent.id,
            input={},
            value={"node_id": "tool_execute"},
            thread_id=str(uuid.uuid4()),
        )
        # 手工把 created_at 改成 25h 前（超 TTL 24h）
        task.pending_confirm["created_at"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        session.add(task)
        await session.commit()
        with pytest.raises(AppError) as exc:
            await TaskService().resume_precheck(session, task)
        assert exc.value.code == 40902


async def test_events_replay_done(tasks_fixture):
    user, agent = tasks_fixture
    async with get_store().session() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        await TaskService().set_done(session, task, {"content": "完成", "token_usage": {"total_tokens": 10}})
        frames = []
        async for frame in _task_event_stream(session, task):
            frames.append(frame)
        assert frames, "至少回放一帧"
        data = frames[0].split("\n\n")[0].split("data: ", 1)[1]
        import json

        event = json.loads(data)
        assert event["type"] == "done"
        assert event["payload"]["message"]["content"] == "完成"


async def _http_task_app(graph):
    app = create_app()
    app.state.graph = graph
    assert not hasattr(app.state, "sessionmaker")
    return app


async def _create_default_route_agent():
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        agent = AgentConfig(
            org_id=DEFAULT_ORG_ID,
            name=f"路由测试助手_{uid}",
            model="fake",
            system_prompt="你是路由测试助手。",
            tools=[],
            max_steps=5,
            status="published",
            is_default=True,
        )
        session.add(agent)
        await session.commit()
    return agent


class _ResumeGraph:
    async def aget_state(self, config):
        return SimpleNamespace(values={"messages": []}, next=("agent_execute",))


async def test_post_tasks_spawns_run_without_sessionmaker_app_state(monkeypatch):
    """真实 POST 路由只依赖 graph，不应读取已删除的数据库工厂状态。"""
    await _create_default_route_agent()
    graph = object()
    captured = []

    def fake_spawn_run(**kwargs):
        captured.append(kwargs)
        return None

    monkeypatch.setattr("app.api.routers.tasks.spawn_run", fake_spawn_run)
    app = await _http_task_app(graph)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/tasks",
            headers={"X-Trace-ID": "route-submit-trace"},
            json={"input": {"message": "hello"}},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    task_id = uuid.UUID(body["data"]["task_id"])
    assert captured == [{"graph": graph, "task_id": task_id, "trace_id": "route-submit-trace"}]
    async with get_store().session() as session:
        task = await TaskRepository(session).get_by_id(task_id)
        assert task is not None
        assert task.user_id == ADMIN_USER.id
        assert task.input == {"message": "hello"}


async def test_json_resume_spawns_run_without_sessionmaker_app_state(monkeypatch):
    agent = await _create_default_route_agent()
    async with get_store().session() as session:
        task = await TaskService().create_waiting_confirm(
            session,
            user=ADMIN_USER,
            agent_id=agent.id,
            input={"message": "resume me"},
            value={"node_id": "tool_execute"},
            thread_id="route-resume-thread",
        )
        task_id = task.id

    graph = _ResumeGraph()
    captured = []

    def fake_spawn_run(**kwargs):
        captured.append(kwargs)
        return None

    monkeypatch.setattr("app.api.routers.tasks.spawn_run", fake_spawn_run)
    app = await _http_task_app(graph)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/tasks/{task_id}/resume",
            headers={"Accept": "application/json", "X-Trace-ID": "route-resume-trace"},
            json={"confirm": {"approved": True}},
        )

    assert response.status_code == 200, response.text
    assert captured == [
        {"graph": graph, "task_id": task_id, "approved": True, "trace_id": "route-resume-trace"}
    ]


async def test_json_resume_denied_preserves_false_approved(monkeypatch):
    agent = await _create_default_route_agent()
    async with get_store().session() as session:
        task = await TaskService().create_waiting_confirm(
            session,
            user=ADMIN_USER,
            agent_id=agent.id,
            input={"message": "deny me"},
            value={"node_id": "tool_execute"},
            thread_id="route-deny-thread",
        )
        task_id = task.id

    graph = _ResumeGraph()
    captured = []

    def fake_spawn_run(**kwargs):
        captured.append(kwargs)
        return None

    monkeypatch.setattr("app.api.routers.tasks.spawn_run", fake_spawn_run)
    app = await _http_task_app(graph)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/tasks/{task_id}/resume",
            headers={"Accept": "application/json", "X-Trace-ID": "route-deny-trace"},
            json={"confirm": {"approved": False}},
        )

    assert response.status_code == 200, response.text
    assert captured == [
        {"graph": graph, "task_id": task_id, "approved": False, "trace_id": "route-deny-trace"}
    ]


def test_submit_task_preserves_extra_input_keys():
    payload = {"message": "hello", "legacy": {"nested": [1, True]}, "count": 0}
    request = SubmitTaskRequest(input=payload)
    assert request.input == payload
    assert request.input is not payload


def test_submit_task_normalizes_attachment_uuid_strings():
    attachment_id = uuid.uuid4()
    request = SubmitTaskRequest(input={"attachment_ids": [str(attachment_id)]})
    assert request.input["attachment_ids"] == [str(attachment_id)]


def test_submit_task_rejects_non_list_attachment_ids_422():
    with pytest.raises(ValidationError):
        SubmitTaskRequest(input={"attachment_ids": str(uuid.uuid4())})


def test_submit_task_rejects_invalid_attachment_uuid_422():
    with pytest.raises(ValidationError):
        SubmitTaskRequest(input={"attachment_ids": ["not-a-uuid"]})


def test_submit_task_rejects_overlong_message():
    with pytest.raises(ValidationError):
        SubmitTaskRequest(input={"message": "x" * (CONTENT_LIMIT + 1)})


async def _create_route_attachment(*, user_id: uuid.UUID, deleted: bool = False) -> Attachment:
    async with get_store().session() as session:
        attachment = Attachment(
            user_id=user_id,
            filename="route.png",
            content_type="image/png",
            size_bytes=4,
            storage_path="",
            status="uploaded",
        )
        if deleted:
            from datetime import UTC, datetime

            attachment.deleted_at = datetime.now(UTC)
        session.add(attachment)
        await session.commit()
    return attachment


@pytest.mark.parametrize("kind", ["foreign", "deleted"])
async def test_submit_task_rejects_inaccessible_attachment_before_task_creation(monkeypatch, kind):
    await _create_default_route_agent()
    attachment = await _create_route_attachment(
        user_id=uuid.uuid4() if kind == "foreign" else ADMIN_USER.id,
        deleted=kind == "deleted",
    )
    before = 0
    async with get_store().session() as session:
        before = await TaskRepository(session).count_for_user(ADMIN_USER.id)

    called = []

    def fake_spawn_run(**kwargs):
        called.append(kwargs)
        return None

    monkeypatch.setattr("app.api.routers.tasks.spawn_run", fake_spawn_run)
    app = await _http_task_app(object())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/tasks",
            json={"input": {"message": "should reject", "attachment_ids": [str(attachment.id)]}},
        )

    assert response.status_code == 200
    assert response.json()["code"] == 40403
    assert called == []
    async with get_store().session() as session:
        assert await TaskRepository(session).count_for_user(ADMIN_USER.id) == before


def test_active_task_summary_excludes_private_task_input():
    """会话冷连接只返回运行摘要，不泄露用户消息/附件等 task.input。"""
    task = Task(
        user_id=ADMIN_USER.id,
        agent_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        status="running",
        input={
            "message": "private user content",
            "attachment_ids": ["secret-attachment"],
            "file_refs": ["private.txt"],
        },
        last_event_seq=7,
    )

    summary = serialize_active_task(task)

    assert summary["id"] == str(task.id)
    assert summary["status"] == "running"
    assert summary["last_event_seq"] == 7
    assert "input" not in summary
    assert "private user content" not in repr(summary)
    assert "secret-attachment" not in repr(summary)
