"""编排器（LangGraph supervisor）协议的单元测试。

不依赖真实大模型与数据库：只验证协议契约、注册表、适配器 context 透传、
图构建，以及编排器的确认门禁。A2A 端到端见 ``tests/test_a2a.py``。
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.logs.core.agents.orchestrator import (
    BaseSubAgent,
    build_supervisor_system_prompt,
    clear_agents,
    get_agent,
    get_agents,
    register_agent,
)


class FakeSubAgent(BaseSubAgent):
    """测试用假子智能体。"""

    name = "fake"
    description = "测试用假子智能体"

    async def stream(self, message: str, *, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        yield f"回答：{message}"


@pytest.fixture(autouse=True)
def _reset_registry() -> Any:
    """每个用例前后清空注册表，避免互相污染。"""
    clear_agents()
    yield
    clear_agents()


def test_register_and_lookup() -> None:
    """注册表：注册后可按名查询，系统提示词包含能力描述。"""
    register_agent(FakeSubAgent())
    assert get_agent("fake") is not None
    assert len(get_agents()) == 1
    assert "fake" in build_supervisor_system_prompt()


def test_clear_agents() -> None:
    """清空注册表。"""
    register_agent(FakeSubAgent())
    clear_agents()
    assert get_agents() == []


@pytest.mark.asyncio
async def test_run_collects_stream() -> None:
    """``run`` 是 ``stream`` 的非流式默认实现，收集全部片段。"""
    agent = FakeSubAgent()
    assert await agent.run("你好") == "回答：你好"


@pytest.mark.asyncio
async def test_ecommerce_adapter_passes_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """电商适配器把 ``context`` 里的 ``user_id`` / ``conversation_id`` 透传给 ``stream_chat``。"""
    from app.logs.core.agents.orchestrator.ecommerce_adapter import ECommerceSubAgent

    captured: dict[str, Any] = {}

    async def fake_stream_chat(user_id: int, message: str, conversation_id: str | None) -> AsyncIterator[str]:
        captured["user_id"] = user_id
        captured["conversation_id"] = conversation_id
        yield "ok"

    monkeypatch.setattr(
        "app.logs.core.agents.orchestrator.ecommerce_adapter.stream_chat",
        fake_stream_chat,
    )
    agent = ECommerceSubAgent()
    chunks = [chunk async for chunk in agent.stream("推荐一双跑鞋", context={"user_id": 7, "conversation_id": "cid"})]
    assert chunks == ["ok"]
    assert captured == {"user_id": 7, "conversation_id": "cid"}


def test_build_graph_with_default_agents() -> None:
    """注册三个子智能体后能构建出 supervisor 图。"""
    from app.logs.core.agents.orchestrator import build_graph
    from app.logs.core.agents.orchestrator.dingtalk_adapter import DingTalkSubAgent
    from app.logs.core.agents.orchestrator.ecommerce_adapter import ECommerceSubAgent
    from app.logs.core.agents.orchestrator.qweather_adapter import QWeatherSubAgent

    register_agent(QWeatherSubAgent())
    register_agent(DingTalkSubAgent())
    register_agent(ECommerceSubAgent())
    names = {agent.name for agent in get_agents()}
    assert {"qweather", "dingtalk", "ecommerce"} <= names
    graph = build_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_get_graph_mounts_checkpointer() -> None:
    """get_graph 编译出的 supervisor 图挂载了短期记忆 Checkpointer。"""
    from app.logs.core.agents.orchestrator import get_graph

    graph = await get_graph()
    assert graph is not None
    assert graph.checkpointer is not None


class ConfirmAgent(BaseSubAgent):
    """测试用「需确认」的子智能体。"""

    name = "confirmable"
    description = "需要确认的假子智能体"
    confirmation_required = True

    async def stream(self, message: str, *, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        yield f"执行：{message}"

    def confirmation_prompt(self, message: str) -> str:
        return f"确定要【{message}】吗？"


def test_needs_confirmation_respects_context() -> None:
    """needs_confirmation：默认需确认，context 带 confirmed 后跳过。"""
    agent = ConfirmAgent()
    assert agent.needs_confirmation(None) is True
    assert agent.needs_confirmation({}) is True
    assert agent.needs_confirmation({"confirmed": True}) is False


def test_confirmation_pending_persists() -> None:
    """store_pending / pop_pending：按 confirm_id 存取，取后删除。"""
    from app.logs.core.agents.orchestrator.confirmation import pop_pending, store_pending

    cid = store_pending("confirmable", "发消息给杨磊说你好", {"user_id": 1})
    pending = pop_pending(cid)
    assert pending is not None
    assert pending.agent_name == "confirmable"
    assert pop_pending(cid) is None


def test_has_pending_marks_unresolved_confirmation() -> None:
    """has_pending：同一会话有未决确认时为 True，处理后为 False。"""
    from app.logs.core.agents.orchestrator.confirmation import has_pending, pop_pending, store_pending

    ctx = {"user_id": 1, "conversation_id": "cid-1"}
    assert has_pending(ctx) is False
    cid = store_pending("confirmable", "发消息", ctx)
    assert has_pending(ctx) is True
    # 不同会话不受影响
    assert has_pending({"user_id": 2, "conversation_id": "cid-2"}) is False
    pop_pending(cid)
    assert has_pending(ctx) is False


def test_sanitize_history_drops_orphan_tool_calls() -> None:
    """回归测试：发给 LLM 前剔除孤儿 assistant(tool_calls) 消息（400 根因防御）。

    异常中断可能在 checkpointer 历史中残留「assistant 带 tool_calls 却无对应
    tool 响应」的残缺序列，下一轮 supervisor 调用会被 LLM 以 400 拒绝；
    ``_sanitize_history`` 必须在调用前剔除这类消息。
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from app.logs.core.agents.orchestrator.engine import _sanitize_history

    complete = AIMessage(
        content="",
        tool_calls=[{"name": "confirmable", "args": {"message": "x"}, "id": "call_1"}],
    )
    orphan = AIMessage(
        content="",
        tool_calls=[{"name": "confirmable", "args": {"message": "y"}, "id": "call_2"}],
    )
    messages = [
        HumanMessage(content="你好"),
        complete,
        ToolMessage(content="已处理", tool_call_id="call_1", name="confirmable"),
        orphan,  # 无对应 tool 响应 → 应被剔除
    ]
    clean = _sanitize_history(messages)
    assert clean == messages[:3]
    # 完整序列原样保留
    assert _sanitize_history(messages[:3]) == messages[:3]


@pytest.mark.asyncio
async def test_confirmation_keeps_history_well_formed(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归测试：确认门禁触发后，会话历史中每条 tool_calls 都必须有对应 tool 响应。

    修复前 tools_node 直接抛 ``ConfirmationRequired`` 中断图，checkpointer 只保留
    supervisor 输出的孤儿 assistant(tool_calls) 消息，下一轮请求把残缺历史发给
    LLM 触发 ``400 insufficient tool messages following tool_calls message``。
    修复后改为占位 tool 响应 + 图跑完统一抛信号，历史始终完整。
    """
    from langchain_core.messages import AIMessage, ToolMessage

    from app.logs.core.agents.orchestrator import engine as engine_mod
    from app.logs.core.agents.orchestrator.confirmation import ConfirmationRequired

    register_agent(ConfirmAgent())

    calls = {"n": 0}

    class FakeLLM:
        def bind_tools(self, tools: Any) -> "FakeLLM":
            return self

        async def ainvoke(self, messages: list[Any]) -> AIMessage:
            calls["n"] += 1
            if calls["n"] <= 2:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "confirmable",
                            "args": {"message": "发消息给丁佳丽说你好"},
                            "id": f"call_{calls['n']}",
                        }
                    ],
                )
            return AIMessage(content="好的，已处理。")

    monkeypatch.setattr(engine_mod, "_get_llm", lambda: FakeLLM())

    # 第一轮：需确认 → 抛 ConfirmationRequired，且历史必须完整
    with pytest.raises(ConfirmationRequired):
        await engine_mod.invoke("发消息给丁佳丽说你好", context={"user_id": 0, "conversation_id": "cid"})

    graph = await engine_mod.get_graph()
    state = await graph.aget_state({"configurable": {"thread_id": "0:cid"}})
    messages = list(state.values["messages"])
    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            following = [m for m in messages[i + 1 :] if isinstance(m, ToolMessage)]
            assert len(following) == len(msg.tool_calls), "tool_calls 缺少对应的 tool 响应"

    # 第二轮：confirmed 透传 → 正常执行并给出最终回答
    out = await engine_mod.invoke(
        "发消息给丁佳丽说你好",
        context={"user_id": 0, "conversation_id": "cid", "confirmed": True},
    )
    assert out == "好的，已处理。"
    final_state = await graph.aget_state({"configurable": {"thread_id": "0:cid"}})
    executed = [
        m
        for m in messages + list(final_state.values["messages"])
        if isinstance(m, ToolMessage) and str(m.content).startswith("执行：")
    ]
    assert executed, "确认后子智能体应真正执行"


def test_customer_service_adapter_metadata() -> None:
    """客服适配器的 name / description / confirmation_required 正确。"""
    from app.logs.core.agents.orchestrator.customer_service_adapter import CustomerServiceSubAgent

    agent = CustomerServiceSubAgent()
    assert agent.name == "customer_service"
    assert "订单查询" in agent.description
    assert agent.confirmation_required is False


def test_a2a_mounts_includes_customer_service() -> None:
    """build_a2a_mounts 能为 CustomerServiceSubAgent 生成独立 A2A 应用。"""
    from app.logs.core.agents.a2a.server import build_a2a_mounts
    from app.logs.core.agents.orchestrator.customer_service_adapter import CustomerServiceSubAgent

    mounts = build_a2a_mounts([CustomerServiceSubAgent()], base_url="http://localhost:8888")
    assert "customer_service" in mounts
    assert mounts["customer_service"] is not None
