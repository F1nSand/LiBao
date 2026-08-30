"""JsonFileSaver 测试：put/get_tuple/list/put_writes 全接口 + 消息序列化 round-trip + checkpoint_ns。"""
from __future__ import annotations

from langchain_core.load import dumps as lc_dumps
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Interrupt

from app.orchestration.checkpointer import JsonFileSaver


def _saver(tmp_path):
    return JsonFileSaver(tmp_path / "checkpoints")


def _checkpoint(cid: str, parent: str | None = None) -> dict:
    return {
        "id": cid,
        "channel_values": {"messages": [HumanMessage(content="hi")], "n": 1},
        "parent_checkpoint_id": parent,
        "pending_sends": [],
    }


async def test_put_and_get_tuple(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t1"}}
    cid = saver.put(config, _checkpoint("c1"), {"source": "test"}, {"messages": "v1"})
    assert cid == "c1"
    tup = await saver.aget_tuple(config)
    assert tup is not None
    assert tup.checkpoint["id"] == "c1"
    # LangChain 消息 round-trip
    msgs = tup.checkpoint["channel_values"]["messages"]
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "hi"


async def test_get_latest_and_parent_config(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t2"}}
    saver.put(config, _checkpoint("c1"), {}, {})
    saver.put(config, _checkpoint("c2", parent="c1"), {}, {})
    tup = await saver.aget_tuple(config)
    assert tup.checkpoint["id"] == "c2"
    assert tup.parent_config["configurable"]["checkpoint_id"] == "c1"


async def test_put_writes_and_pending(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t3"}}
    saver.put(config, _checkpoint("c1"), {}, {})
    cfg = {"configurable": {"thread_id": "t3", "checkpoint_id": "c1"}}
    saver.put_writes(cfg, [("messages", AIMessage(content="tool result"))], task_id="task-1")
    tup = await saver.aget_tuple(config)
    assert tup.pending_writes == [("task-1", "messages", tup.pending_writes[0][2])]
    assert isinstance(tup.pending_writes[0][2], AIMessage)


async def test_error_pending_write_roundtrip_is_loadable(tmp_path):
    """节点异常写入 checkpoint 后必须可恢复，不能让同一 thread 永久中毒。"""
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-error"}}
    saver.put(config, _checkpoint("c1"), {"source": "loop", "step": 1}, {})
    cfg = {"configurable": {"thread_id": "t-error", "checkpoint_id": "c1"}}
    saver.put_writes(cfg, [("__error__", RuntimeError("boom"))], task_id="task-error")

    tup = await saver.aget_tuple(config)

    assert tup is not None
    assert len(tup.pending_writes) == 1
    assert tup.pending_writes[0][:2] == ("task-error", "__error__")


async def test_get_failed_config_returns_explicit_error_checkpoint(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-failed-config"}}
    saver.put(config, _checkpoint("c1"), {"source": "input"}, {})
    saver.put(config, _checkpoint("c2", parent="c1"), {"source": "loop"}, {})
    saver.put_writes(
        {"configurable": {"thread_id": "t-failed-config", "checkpoint_id": "c2"}},
        [("__error__", RuntimeError("transport"))],
        task_id="task-error",
    )

    failed = await saver.aget_failed_config(config)
    assert failed == {"configurable": {"thread_id": "t-failed-config", "checkpoint_id": "c2"}}


async def test_get_failed_config_is_thread_scoped_and_none_without_error(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-no-error"}}
    saver.put(config, _checkpoint("c1"), {}, {})
    assert await saver.aget_failed_config(config) is None
    other = {"configurable": {"thread_id": "other"}}
    assert await saver.aget_failed_config(other) is None


async def test_interrupt_pending_write_roundtrip_is_loadable(tmp_path):
    """文件 checkpoint 必须支持真实 LangGraph 中断后的 resume。"""
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-interrupt"}}
    saver.put(config, _checkpoint("c1"), {"source": "loop", "step": 1}, {})
    cfg = {"configurable": {"thread_id": "t-interrupt", "checkpoint_id": "c1"}}
    interrupt = Interrupt(value={"tool_name": "shell", "confirm_required": True}, id="interrupt-1")
    saver.put_writes(cfg, [("__interrupt__", [interrupt])], task_id="task-interrupt")

    tup = await saver.aget_tuple(config)

    assert tup is not None
    assert len(tup.pending_writes) == 1
    task_id, channel, value = tup.pending_writes[0]
    assert task_id == "task-interrupt" and channel == "__interrupt__"
    assert isinstance(value, list) and isinstance(value[0], Interrupt)
    assert value[0].id == "interrupt-1"
    assert value[0].value["tool_name"] == "shell"


async def test_legacy_interrupt_pending_write_is_loadable(tmp_path):
    """修复前已落盘的 not_implemented 中断也必须可恢复。"""
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-legacy-interrupt"}}
    saver.put(config, _checkpoint("c1"), {"source": "loop", "step": 1}, {})
    legacy = Interrupt(value={"tool_name": "shell", "confirm_required": True}, id="legacy-1")
    data = saver._load(saver._path(config))
    data["checkpoints"]["c1"]["writes"]["task-interrupt"] = [
        ["__interrupt__", lc_dumps([legacy])]
    ]
    saver._save(saver._path(config), data)

    tup = await saver.aget_tuple(config)

    assert tup is not None
    assert isinstance(tup.pending_writes[0][2][0], Interrupt)
    assert tup.pending_writes[0][2][0].id == "legacy-1"


async def test_legacy_not_implemented_error_write_is_loadable(tmp_path):
    """兼容旧版已落盘的 not_implemented 异常，现有中毒会话应可自动恢复。"""
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-legacy-error"}}
    saver.put(config, _checkpoint("c1"), {"source": "loop", "step": 1}, {})
    path = saver._path(config)
    data = saver._load(path)
    data["checkpoints"]["c1"]["writes"]["task-error"] = [
        ["__error__", lc_dumps(RuntimeError("legacy boom"))]
    ]
    saver._save(path, data)

    tup = await saver.aget_tuple(config)

    assert tup is not None
    assert tup.pending_writes[0][:2] == ("task-error", "__error__")


async def test_list_before_limit(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t4"}}
    for i in range(5):
        saver.put(config, _checkpoint(f"c{i}"), {}, {})
    items = list(saver.list(config, limit=2))
    assert [t.checkpoint["id"] for t in items] == ["c4", "c3"]
    before = {"configurable": {"thread_id": "t4", "checkpoint_id": "c3"}}
    items2 = list(saver.list(config, before=before))
    # before 语义：c3 之前（时间更早）的记录，新→旧
    assert [t.checkpoint["id"] for t in items2] == ["c2", "c1", "c0"]


async def test_checkpoint_ns_isolation(tmp_path):
    saver = _saver(tmp_path)
    ns1 = {"configurable": {"thread_id": "t5", "checkpoint_ns": "ns1"}}
    ns2 = {"configurable": {"thread_id": "t5", "checkpoint_ns": "ns2"}}
    saver.put(ns1, _checkpoint("a1"), {}, {})
    saver.put(ns2, _checkpoint("b1"), {}, {})
    t1 = await saver.aget_tuple(ns1)
    t2 = await saver.aget_tuple(ns2)
    assert t1.checkpoint["id"] == "a1"
    assert t2.checkpoint["id"] == "b1"


async def test_run_bounds_are_indexed_by_code_checkpoint_id(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-run-bounds"}}
    saver.put(config, _checkpoint("c0"), {"source": "input"}, {})
    saver.put(
        {"configurable": {"thread_id": "t-run-bounds", "code_checkpoint_id": "code-1"}},
        _checkpoint("c1", parent="c0"),
        {"source": "input"},
        {},
    )
    saver.put(
        {"configurable": {"thread_id": "t-run-bounds", "code_checkpoint_id": "code-1"}},
        _checkpoint("c2", parent="c1"),
        {"source": "loop"},
        {},
    )

    parent, output = await saver.aget_run_bounds(config, "code-1")

    assert parent == "c0"
    assert output == "c2"


async def test_failed_run_bounds_skip_failed_input_checkpoint(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-failed-run"}}
    saver.put(config, _checkpoint("c0"), {"source": "loop"}, {})
    run_config = {"configurable": {"thread_id": "t-failed-run", "code_checkpoint_id": "code-2"}}
    saver.put(run_config, _checkpoint("c1", parent="c0"), {"source": "input"}, {})
    saver.put_writes(
        {"configurable": {"thread_id": "t-failed-run", "checkpoint_id": "c1"}},
        [("__error__", RuntimeError("boom"))],
        "task-1",
    )

    parent, output = await saver.aget_run_bounds(config, "code-2")

    assert parent == "c0"
    assert output == "c0"


async def test_explicit_checkpoint_wins_over_start_graph_from_root(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-root"}}
    saver.put(config, _checkpoint("c1"), {}, {})

    root = await saver.aget_tuple(
        {"configurable": {"thread_id": "t-root", "start_graph_from_root": True}}
    )
    explicit = await saver.aget_tuple(
        {
            "configurable": {
                "thread_id": "t-root",
                "checkpoint_id": "c1",
                "start_graph_from_root": True,
            }
        }
    )

    assert root is None
    assert explicit is not None
    assert explicit.checkpoint["id"] == "c1"


async def test_delete_thread(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t6"}}
    saver.put(config, _checkpoint("c1"), {}, {})
    saver.delete_thread("t6")
    assert await saver.aget_tuple(config) is None


async def test_configurable_image_payload_is_not_serialized(tmp_path):
    """图片 payload 只属于运行时 configurable，不得进入 checkpoint 文件。"""
    saver = _saver(tmp_path)
    secret = "task-image-base64-sentinel"
    config = {
        "configurable": {
            "thread_id": "t-image",
            "image_payload": {"att-1": {"data_b64": secret}},
            "current_image_ids": {"att-1"},
        }
    }
    saver.put(config, _checkpoint("c1"), {}, {})
    assert secret not in saver._path(config).read_text(encoding="utf-8")


async def test_typed_envelope_is_written_for_checkpoint_and_interrupt(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-typed"}}
    saver.put(config, _checkpoint("c1"), {"source": "test"}, {})
    saver.put_writes(
        {"configurable": {"thread_id": "t-typed", "checkpoint_id": "c1"}},
        [("__interrupt__", [Interrupt(value={"tool_name": "shell"}, id="i1")])],
        task_id="task-typed",
    )
    raw = saver._path(config).read_text(encoding="utf-8")
    assert "langgraph-typed-v1" in raw
    assert "not_implemented" not in raw
    tup = await saver.aget_tuple(config)
    assert isinstance(tup.pending_writes[0][2][0], Interrupt)


async def test_legacy_and_typed_values_can_coexist_without_rewrite(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t-mixed"}}
    saver.put(config, _checkpoint("c1"), {"source": "test"}, {})
    path = saver._path(config)
    before = path.read_text(encoding="utf-8")
    data = saver._load(path)
    data["checkpoints"]["legacy"] = {
        "checkpoint": lc_dumps(_checkpoint("legacy")),
        "metadata": lc_dumps({"source": "legacy"}),
        "writes": {},
    }
    saver._save(path, data)
    assert (await saver.aget_tuple(config)).checkpoint["id"] == "legacy"
    assert before != path.read_text(encoding="utf-8")
