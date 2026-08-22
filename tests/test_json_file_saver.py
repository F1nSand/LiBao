"""JsonFileSaver 测试：put/get_tuple/list/put_writes 全接口 + 消息序列化 round-trip + checkpoint_ns。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

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


async def test_delete_thread(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "t6"}}
    saver.put(config, _checkpoint("c1"), {}, {})
    saver.delete_thread("t6")
    assert await saver.aget_tuple(config) is None
