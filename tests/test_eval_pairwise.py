"""M5 配对比较 + 评估端点补齐测试（DB-backed）。"""
from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.orchestration.graph import build_graph
from app.services.eval import EvalService, run_eval
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Org, User
from tests.conftest import requires_db

pytestmark = requires_db


class FakeEvalModel:
    """同一模型作被测与裁判（按 prompt 区分）。judge_fail_inputs 指定判定失败的 input 子串。"""

    def __init__(self, judge_pass=True, fail_inputs: list[str] | None = None):
        self.judge_pass = judge_pass
        self.fail_inputs = fail_inputs or []

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        text = "".join(str(getattr(m, "content", "") or "") for m in messages)
        if "你是评估裁判" in text:
            fail = any(fi in text for fi in self.fail_inputs)
            passed = self.judge_pass and not fail
            return AIMessage(content=json.dumps({"pass": passed, "score": 0.5 if passed else 0.0}))
        return AIMessage(content="这是评估回答。")


@pytest.fixture
async def eval_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-pw-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"pw_{uid}", password_hash="hashed", name="E", role="admin", org_id=org.id)
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


async def test_pairwise_win_lose_tie(eval_fixture):
    sessionmaker, user = eval_fixture
    svc = EvalService()
    async with get_store().session(sessionmaker) as session:
        s = await svc.create_set(session, user, "配对集")
        await svc.add_case(session, user, s.id, "1+1", "2")  # base pass / cand fail → lose
        await svc.add_case(session, user, s.id, "2+2", "4")  # base fail / cand pass → win
        await svc.add_case(session, user, s.id, "3+3", "6")  # both pass → tie
        baseline = await svc.create_run(session, user, s.id)
        candidate = await svc.create_run(session, user, s.id, baseline_run_id=baseline.id)
        baseline_id, candidate_id = baseline.id, candidate.id

    graph = build_graph()
    # 基线：2+2 判失败（其余通过）；候选：1+1 判失败（其余通过）→ c1 lose / c2 win / c3 tie
    await run_eval(graph, sessionmaker, baseline_id, model_override=FakeEvalModel(fail_inputs=["2+2"]))
    await run_eval(graph, sessionmaker, candidate_id, model_override=FakeEvalModel(fail_inputs=["1+1"]))

    async with get_store().session(sessionmaker) as session:
        pw = await svc.pairwise(session, user, candidate_id, baseline_id)
        assert pw["summary"]["wins"] == 1  # 2+2: base fail / cand pass
        assert pw["summary"]["losses"] == 1  # 1+1: base pass / cand fail
        assert pw["summary"]["ties"] == 1  # 3+3: both pass
        assert pw["summary"]["baseline_pass_rate"] == round(2 / 3, 4)
        assert pw["summary"]["candidate_pass_rate"] == round(2 / 3, 4)
        assert pw["summary"]["delta"] == 0.0
        assert len(pw["matrix"]) == 3
        outcomes = {m["input"]: m["outcome"] for m in pw["matrix"]}
        assert outcomes["1+1"] == "lose" and outcomes["2+2"] == "win" and outcomes["3+3"] == "tie"


async def test_eval_case_layer_and_endpoints(eval_fixture):
    sessionmaker, user = eval_fixture
    svc = EvalService()
    async with get_store().session(sessionmaker) as session:
        s = await svc.create_set(session, user, "端点集")
        c = await svc.add_case(session, user, s.id, "1+1", "2", layer="L1")
        assert c.layer == "L1"

        # list_cases 带 layer
        cases = await svc.list_cases(session, user, s.id)
        assert len(cases) == 1 and cases[0]["layer"] == "L1"

        # patch_set
        patched = await svc.patch_set(session, user, s.id, name="端点集2", description="新描述")
        assert patched.name == "端点集2"

        # create_run 存 baseline（在删集前，验证 409 守卫）
        b = await svc.create_run(session, user, s.id)
        c_run = await svc.create_run(session, user, s.id, baseline_run_id=b.id)
        assert c_run.baseline_run_id == b.id
        with pytest.raises(Exception) as exc:
            await svc.delete_set(session, user, s.id)  # 有运行历史 → 409，不可删
        assert exc.value.code == 40904

        # delete_case
        await svc.delete_case(session, user, s.id, c.id)
        assert await svc.list_cases(session, user, s.id) == []


async def test_run_detail_includes_latency_cost(eval_fixture):
    sessionmaker, user = eval_fixture
    svc = EvalService()
    async with get_store().session(sessionmaker) as session:
        s = await svc.create_set(session, user, "细节集")
        await svc.add_case(session, user, s.id, "1+1", "2")
        run = await svc.create_run(session, user, s.id)
        run_id = run.id
    graph = build_graph()
    await run_eval(graph, sessionmaker, run_id, model_override=FakeEvalModel())
    async with get_store().session(sessionmaker) as session:
        detail = await svc.get_run_detail(session, user, run_id)
        r = detail["results"][0]
        assert "latency_ms" in r and r["latency_ms"] is not None
        assert "cost" in r and r["cost"] == 0.0  # Fake 无 usage_metadata → 估算 0
