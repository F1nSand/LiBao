"""2g evals 测试（DB-backed，FakeEvalModel）：集/用例 CRUD + run_eval 后台链 + pass_rate + 结果落库。"""
from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.core.security import hash_password
from app.orchestration.graph import build_graph
from app.services.eval import EvalService, _parse_judge, run_eval
from app.storage.db import init_db
from app.storage.models import AgentConfig, Org, User
from tests.conftest import requires_db

pytestmark = requires_db


class FakeEvalModel:
    """同一模型实例同时作被测模型与裁判（按 prompt 区分）。"""

    def __init__(self, content="这是评估回答。", judge_pass: bool = True, judge_score: float = 0.9):
        self.content = content
        self.judge_pass = judge_pass
        self.judge_score = judge_score

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        text = "".join(str(getattr(m, "content", "") or "") for m in messages)
        if "你是评估裁判" in text:
            return AIMessage(content=json.dumps({"pass": self.judge_pass, "score": self.judge_score}))
        return AIMessage(content=self.content)


@pytest.fixture
async def eval_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-eval-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"eval_{uid}", password_hash=hash_password("x"), name="E", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id, name="评估助手", model="fake", system_prompt="你是测试助手。", tools=[],
            max_steps=5, status="published",
        )
        session.add(agent)
        await session.commit()
    yield sessionmaker, user
    await engine.dispose()


def test_parse_judge():
    assert _parse_judge('{"pass": true, "score": 0.9}') == {"pass": True, "score": 0.9}
    assert _parse_judge('```json\n{"pass": false}\n```') == {"pass": False}
    assert _parse_judge("no json") == {}


async def test_eval_set_and_case_crud(eval_fixture):
    sessionmaker, user = eval_fixture
    svc = EvalService()
    async with sessionmaker() as session:
        s = await svc.create_set(session, user, "回归集", "冒烟")
        await svc.add_case(session, user, s.id, "1+1", "2")
        c2 = await svc.add_case(session, user, s.id, "中国的首都", "北京")
        patched = await svc.patch_case(session, user, s.id, c2.id, False)
        assert patched.active is False
        sets = await svc.list_sets(session, user)
        assert sets[0]["name"] == "回归集"
        assert sets[0]["case_count"] == 2  # 全部用例计数（含停用）


async def test_run_eval_completes_with_pass_rate(eval_fixture):
    sessionmaker, user = eval_fixture
    svc = EvalService()
    async with sessionmaker() as session:
        s = await svc.create_set(session, user, "回归集")
        await svc.add_case(session, user, s.id, "1+1", "2")
        await svc.add_case(session, user, s.id, "苹果的颜色", "红色")
        run = await svc.create_run(session, user, s.id)
        run_id = run.id
    graph = build_graph()
    await run_eval(graph, sessionmaker, run_id, model_override=FakeEvalModel(judge_pass=True))
    async with sessionmaker() as session:
        detail = await svc.get_run_detail(session, run_id)
        assert detail["run"]["status"] == "done"
        assert detail["run"]["pass_rate"] == 1.0
        assert len(detail["results"]) == 2
        assert detail["results"][0]["actual"] == "这是评估回答。"
        assert detail["results"][0]["pass"] is True


async def test_run_eval_failed_judge_counts_fail(eval_fixture):
    sessionmaker, user = eval_fixture
    svc = EvalService()
    async with sessionmaker() as session:
        s = await svc.create_set(session, user, "负例集")
        await svc.add_case(session, user, s.id, "问", "期望")
        run = await svc.create_run(session, user, s.id)
        run_id = run.id
    graph = build_graph()
    await run_eval(graph, sessionmaker, run_id, model_override=FakeEvalModel(judge_pass=False))
    async with sessionmaker() as session:
        detail = await svc.get_run_detail(session, run_id)
        assert detail["run"]["status"] == "done"
        assert detail["run"]["pass_rate"] == 0.0
        assert detail["results"][0]["pass"] is False
