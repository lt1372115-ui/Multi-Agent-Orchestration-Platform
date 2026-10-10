"""对外公告发布审批智能体（Human-in-the-loop）的冒烟测试。

不依赖 PostgreSQL / 钉钉 / 大模型：
- 图核心逻辑（check 风险分流、interrupt 暂停、四种人工响应）用 MemorySaver 验证；
- 路由已注册到 ``/api/v1/announcements``。
"""

from collections.abc import Mapping
from typing import Any, cast

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.logs.core.agents.announcement import graph as graph_module
from app.logs.core.agents.announcement.graph import _check_node, build_graph
from app.logs.core.agents.announcement.state import AnnouncementState
from app.main import app


def _initial_state(**overrides: Any) -> AnnouncementState:
    """构造一条初始公告状态，可用关键字覆盖任意字段。"""
    state: dict[str, Any] = {
        "announcement_id": 1,
        "thread_id": "announcement:t1",
        "title": "测试公告",
        "content": "这是一条测试公告",
        "risk_level": "high",
        "submitter": "张三",
        "approved": False,
        "status": "submitted",
    }
    state.update(overrides)
    return cast(AnnouncementState, state)


def _memory_graph() -> Any:
    """用进程内检查点构建图，避免测试依赖 PostgreSQL。"""
    return build_graph(checkpointer=MemorySaver())


async def _fake_publish(title: str, content: str) -> str:
    """替身发布函数，避免测试真的调用钉钉。"""
    return "ok"


async def _fake_notify(state: Mapping[str, Any]) -> str:
    """替身通知函数，避免测试真的推送机器人消息。"""
    return "ok"


def test_announcement_route_is_registered() -> None:
    """路由应注册到 /api/v1/announcements 及其 respond 子路径。"""
    paths = app.openapi()["paths"]
    assert "/api/v1/announcements" in paths
    assert "/api/v1/announcements/{announcement_id}/respond" in paths


def test_check_node_low_risk_auto_approves() -> None:
    """低风险且无敏感词的公告自动批准。"""
    result = _check_node(_initial_state(risk_level="low"))
    assert result["approved"] is True
    assert result["status"] == "approved"


def test_check_node_high_risk_pending() -> None:
    """高风险公告进入待审批。"""
    result = _check_node(_initial_state())
    assert result["approved"] is False
    assert result["status"] == "pending_approval"


def test_check_node_sensitive_keyword_escalates() -> None:
    """低风险但命中敏感词也会升级为人工审批。"""
    result = _check_node(_initial_state(risk_level="low", content="全体注意明天放假"))
    assert result["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_graph_interrupts_on_high_risk(monkeypatch: pytest.MonkeyPatch) -> None:
    """高风险公告执行到 human_review 应暂停（返回 __interrupt__）。"""
    monkeypatch.setattr(graph_module, "publish_notice_to_group", _fake_publish)
    monkeypatch.setattr(graph_module, "notify_pending_approval", _fake_notify)
    graph = _memory_graph()
    result = await graph.ainvoke(_initial_state(), config={"configurable": {"thread_id": "t1"}})
    assert result.get("__interrupt__") is not None


@pytest.mark.asyncio
async def test_graph_resume_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    """恢复 approve 后发布成功。"""
    monkeypatch.setattr(graph_module, "publish_notice_to_group", _fake_publish)
    monkeypatch.setattr(graph_module, "notify_pending_approval", _fake_notify)
    graph = _memory_graph()
    config = {"configurable": {"thread_id": "t2"}}
    first = await graph.ainvoke(_initial_state(), config=config)
    assert first.get("__interrupt__") is not None
    result = await graph.ainvoke(Command(resume={"action": "approve"}), config=config)
    assert result["status"] == "published"
    assert result["approved"] is True


@pytest.mark.asyncio
async def test_graph_resume_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    """恢复 reject 后拒绝发布。"""
    monkeypatch.setattr(graph_module, "publish_notice_to_group", _fake_publish)
    monkeypatch.setattr(graph_module, "notify_pending_approval", _fake_notify)
    graph = _memory_graph()
    config = {"configurable": {"thread_id": "t3"}}
    await graph.ainvoke(_initial_state(), config=config)
    result = await graph.ainvoke(Command(resume={"action": "reject", "note": "内容敏感"}), config=config)
    assert result["status"] == "rejected"
    assert result["approved"] is False


@pytest.mark.asyncio
async def test_graph_resume_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """恢复 cancel 后整条作废。"""
    monkeypatch.setattr(graph_module, "publish_notice_to_group", _fake_publish)
    monkeypatch.setattr(graph_module, "notify_pending_approval", _fake_notify)
    graph = _memory_graph()
    config = {"configurable": {"thread_id": "t4"}}
    await graph.ainvoke(_initial_state(), config=config)
    result = await graph.ainvoke(Command(resume={"action": "cancel"}), config=config)
    assert result["status"] == "canceled"


@pytest.mark.asyncio
async def test_graph_resume_edit_updates_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """恢复 edit 后用修改后的标题发布。"""
    monkeypatch.setattr(graph_module, "publish_notice_to_group", _fake_publish)
    monkeypatch.setattr(graph_module, "notify_pending_approval", _fake_notify)
    graph = _memory_graph()
    config = {"configurable": {"thread_id": "t5"}}
    await graph.ainvoke(_initial_state(), config=config)
    result = await graph.ainvoke(Command(resume={"action": "edit", "title": "修改后的标题"}), config=config)
    assert result["status"] == "published"
    assert result["title"] == "修改后的标题"


@pytest.mark.asyncio
async def test_graph_low_risk_publishes_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    """低风险公告跳过人工审批直接发布，不产生 __interrupt__。"""
    monkeypatch.setattr(graph_module, "publish_notice_to_group", _fake_publish)
    graph = _memory_graph()
    result = await graph.ainvoke(_initial_state(risk_level="low"), config={"configurable": {"thread_id": "t6"}})
    assert "__interrupt__" not in result
    assert result["status"] == "published"
