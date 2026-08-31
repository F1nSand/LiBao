"""会话 Task 关联、冷连接查询与单会话单活约束。"""
from __future__ import annotations

import asyncio
import uuid

import httpx

from app.api.main import create_app
from app.core.errors import ERR_TASK_RUNNING, AppError
from app.services.task import TaskService
from app.storage.constants import ADMIN_USER
from app.storage.file.store import get_store
from app.storage.models.conversation import Conversation
from app.storage.repositories.conversation import ConversationRepository
from app.storage.repositories.task import TaskRepository


async def _create_conversation() -> Conversation:
    async with get_store().session() as session:
        conversation = await ConversationRepository(session).create(
            user_id=ADMIN_USER.id,
            agent_id=uuid.uuid4(),
            title="任务连接测试",
        )
        await session.commit()
        return conversation


async def test_current_task_matches_legacy_input_binding_and_recoverable_fallback():
    conversation = await _create_conversation()
    async with get_store().session() as session:
        task = await TaskRepository(session).create(
            user_id=ADMIN_USER.id,
            agent_id=uuid.uuid4(),
            input={"conversation_id": str(conversation.id), "message": "legacy"},
            status="failed",
        )
        task.error = {"code": 60009, "message": "restart", "recoverable": True}
        await session.commit()

        current, relation = await TaskRepository(session).get_current_for_conversation(
            ADMIN_USER.id, conversation.id
        )

    assert current is not None and current.id == task.id
    assert relation == "recoverable"


async def test_submit_for_conversation_allows_only_one_nonterminal_task():
    conversation = await _create_conversation()

    async def submit_once():
        async with get_store().session() as session:
            return await TaskService().submit_for_conversation(
                session,
                ADMIN_USER,
                uuid.uuid4(),
                conversation.id,
                {"conversation_id": str(conversation.id), "message": "hello"},
            )

    results = await asyncio.gather(submit_once(), submit_once(), return_exceptions=True)

    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, AppError)]
    assert len(successes) == 1
    assert len(failures) == 1 and failures[0].code == ERR_TASK_RUNNING


async def test_active_task_endpoint_returns_safe_summary_for_owner():
    conversation = await _create_conversation()
    async with get_store().session() as session:
        task = await TaskService().submit_for_conversation(
            session,
            ADMIN_USER,
            uuid.uuid4(),
            conversation.id,
            {
                "conversation_id": str(conversation.id),
                "message": "do not expose",
                "attachment_ids": ["private"],
            },
        )
        task_id = str(task.id)

    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/conversations/{conversation.id}/active-task")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["conversation_id"] == str(conversation.id)
    assert body["data"]["relation"] == "active"
    assert body["data"]["task"]["id"] == task_id
    assert "input" not in body["data"]["task"]
    assert "do not expose" not in response.text


async def test_active_task_endpoint_returns_null_without_task():
    conversation = await _create_conversation()
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/conversations/{conversation.id}/active-task")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "conversation_id": str(conversation.id),
        "relation": None,
        "task": None,
    }
