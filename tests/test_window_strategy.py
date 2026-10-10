"""短期记忆窗口策略（``trim`` / ``compact``）的单元测试。

不调用大模型、不依赖 Postgres / Redis：用假记忆存储与假摘要 LLM，验证
「最近条数 + token 预算」窗口、滚动摘要写入画像，以及摘要失败时的硬上限兜底。
"""

from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.logs.core.agents import runtime, window
from app.logs.core.agents.ecommerce.memory.base import UserProfile
from app.logs.core.agents.window import (
    HybridWindowStrategy,
    SummaryWindowStrategy,
    TokenBudgetWindowStrategy,
    TruncateWindowStrategy,
    build_window_strategy,
)


class _FakeStore:
    """只实现窗口摘要用到的最小记忆接口，并记录写入行为。"""

    def __init__(self, profile: UserProfile | None = None, *, available: bool = True) -> None:
        self.profile = profile
        self.available = available
        self.upserts: list[UserProfile] = []
        self.touches: list[bool] = []

    async def get_profile(self, user_id: int) -> UserProfile | None:
        if not self.available:
            raise RuntimeError("记忆后端不可用")
        return self.profile

    async def upsert_profile(self, profile: UserProfile, touch: bool = True) -> None:
        if not self.available:
            raise RuntimeError("记忆后端不可用")
        self.upserts.append(profile)
        self.touches.append(touch)
        self.profile = profile


class _FakeLLM:
    """假摘要模型：记录收到的 prompt，返回固定摘要文本。"""

    def __init__(self, text: str = "滚动摘要") -> None:
        self.text = text
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str) -> AIMessage:
        self.prompts.append(prompt)
        return AIMessage(self.text)


def _unavailable_llm() -> Any:
    """模拟摘要模型不可用（如未配置 DeepSeek）。"""
    raise RuntimeError("DeepSeek 配置不完整，无法执行窗口摘要")


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    """把 runtime 的记忆存储单例替换为假实现。"""
    store = _FakeStore()
    monkeypatch.setattr(runtime, "get_memory_store", lambda: store)
    return store


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> _FakeLLM:
    """把摘要模型替换为假实现，避免真实网络请求。"""
    llm = _FakeLLM()
    monkeypatch.setattr(window, "_build_summary_llm", lambda: llm)
    return llm


def _tool(content: str, message_id: str) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="call-1", id=message_id)


def _ai_with_tool_call(message_id: str) -> AIMessage:
    return AIMessage(
        "",
        tool_calls=[{"name": "search_products", "args": {"query": "跑鞋"}, "id": "call-1", "type": "tool_call"}],
        id=message_id,
    )


def test_build_window_strategy_maps_every_config_value() -> None:
    """四个策略名各自映射到对应实现，未识别的取值回退到截断策略。"""
    assert type(build_window_strategy("truncate")) is TruncateWindowStrategy
    assert type(build_window_strategy("token")) is TokenBudgetWindowStrategy
    assert type(build_window_strategy("summary")) is SummaryWindowStrategy
    assert type(build_window_strategy("hybrid")) is HybridWindowStrategy
    assert type(build_window_strategy("unknown")) is TruncateWindowStrategy


def test_hybrid_trim_truncates_tool_output_and_keeps_recent_messages() -> None:
    """trim 会截断过长的工具输出，并只保留最近 N 条消息。"""
    strategy = HybridWindowStrategy(keep_messages=4, max_tokens=5000, tool_max_chars=10, hard_limit=10)
    raw = "很长的工具输出" * 5
    messages: list[BaseMessage] = [
        HumanMessage("第一个问题", id="m1"),
        _tool(raw, "m2"),
        AIMessage("回答", id="m3"),
        HumanMessage("新问题", id="m4"),
    ]

    kept = strategy.trim(messages)

    assert [message.id for message in kept] == ["m1", "m2", "m3", "m4"]
    assert kept[1].content != raw
    assert "已截断" in kept[1].content


def test_hybrid_trim_keeps_only_recent_messages() -> None:
    """超出条数窗口的旧消息不再注入模型。"""
    strategy = HybridWindowStrategy(keep_messages=2, max_tokens=5000, tool_max_chars=0, hard_limit=10)
    messages: list[BaseMessage] = [
        HumanMessage("第一个问题", id="m1"),
        AIMessage("第一次回答", id="m2"),
        HumanMessage("新问题", id="m3"),
    ]

    assert [message.id for message in strategy.trim(messages)] == ["m2", "m3"]


def test_trim_drops_orphan_tool_message_at_window_start() -> None:
    """窗口左边界落在工具结果上时丢弃该消息，避免出现无前置工具调用的结果消息。"""
    strategy = HybridWindowStrategy(keep_messages=2, max_tokens=5000, tool_max_chars=0, hard_limit=10)
    messages: list[BaseMessage] = [
        HumanMessage("想买跑鞋", id="m1"),
        _ai_with_tool_call("m2"),
        _tool("1. 轻便透气跑步鞋", "m3"),
        AIMessage("推荐这双", id="m4"),
    ]

    assert [message.id for message in strategy.trim(messages)] == ["m4"]


def test_trim_keeps_complete_tool_pair() -> None:
    """窗口同时覆盖工具调用与其结果时，整对消息都保留。"""
    strategy = HybridWindowStrategy(keep_messages=3, max_tokens=5000, tool_max_chars=0, hard_limit=10)
    messages: list[BaseMessage] = [
        HumanMessage("想买跑鞋", id="m1"),
        _ai_with_tool_call("m2"),
        _tool("1. 轻便透气跑步鞋", "m3"),
        AIMessage("推荐这双", id="m4"),
    ]

    assert [message.id for message in strategy.trim(messages)] == ["m2", "m3", "m4"]


def test_hybrid_trim_applies_token_budget() -> None:
    """单条消息就逼近预算时，只保留最新的那一条。"""
    strategy = HybridWindowStrategy(keep_messages=10, max_tokens=150, tool_max_chars=0, hard_limit=20)
    messages: list[BaseMessage] = [HumanMessage("很" * 100, id="m1"), HumanMessage("好" * 100, id="m2")]

    assert [message.id for message in strategy.trim(messages)] == ["m2"]


@pytest.mark.asyncio
async def test_hybrid_compact_summarizes_overflow_into_profile(fake_store: _FakeStore, fake_llm: _FakeLLM) -> None:
    """compact 把窗口外的旧消息总结进画像，并返回这些消息的删除指令。"""
    strategy = HybridWindowStrategy(keep_messages=2, max_tokens=5000, tool_max_chars=0, hard_limit=10)
    messages: list[BaseMessage] = [
        HumanMessage("我要买跑鞋", id="m1"),
        AIMessage("预算多少", id="m2"),
        HumanMessage("500 以内", id="m3"),
    ]

    removed = await strategy.compact(messages, user_id=7)

    assert [message.id for message in removed] == ["m1"]
    assert fake_store.profile is not None
    assert fake_store.profile.history_summary == "滚动摘要"
    # 后台整理记忆不应刷新 last_interaction
    assert fake_store.touches == [False]
    assert "我要买跑鞋" in fake_llm.prompts[0]


@pytest.mark.asyncio
async def test_hybrid_compact_rolls_previous_summary(monkeypatch: pytest.MonkeyPatch, fake_llm: _FakeLLM) -> None:
    """已有画像摘要时滚动叠加，且不覆盖画像里的其它字段。"""
    store = _FakeStore(UserProfile(user_id=7, name="小林", history_summary="用户偏好轻量跑鞋"))
    monkeypatch.setattr(runtime, "get_memory_store", lambda: store)
    strategy = HybridWindowStrategy(keep_messages=1, max_tokens=5000, tool_max_chars=0, hard_limit=10)
    messages: list[BaseMessage] = [HumanMessage("旧问题", id="m1"), HumanMessage("新问题", id="m2")]

    removed = await strategy.compact(messages, user_id=7)

    assert [message.id for message in removed] == ["m1"]
    assert "此前对话摘要：用户偏好轻量跑鞋" in fake_llm.prompts[0]
    assert store.profile is not None
    assert store.profile.history_summary == "滚动摘要"
    assert store.profile.name == "小林"


@pytest.mark.asyncio
async def test_hybrid_compact_window_follows_token_budget(fake_store: _FakeStore, fake_llm: _FakeLLM) -> None:
    """压缩窗口由「条数 + token 预算」共同决定，超出预算的旧消息同样会被压缩。"""
    strategy = HybridWindowStrategy(keep_messages=10, max_tokens=150, tool_max_chars=0, hard_limit=20)
    messages: list[BaseMessage] = [
        HumanMessage("很" * 100, id="m1"),
        HumanMessage("好" * 100, id="m2"),
        HumanMessage("行" * 100, id="m3"),
    ]

    removed = await strategy.compact(messages, user_id=7)

    assert [message.id for message in removed] == ["m1", "m2"]
    assert fake_store.profile is not None
    assert fake_store.profile.history_summary == "滚动摘要"


@pytest.mark.asyncio
async def test_compact_keeps_messages_when_summary_fails_below_hard_limit(
    fake_store: _FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """摘要失败且未达硬上限：本轮不删除，等下一轮重试，避免信息丢失。"""
    monkeypatch.setattr(window, "_build_summary_llm", _unavailable_llm)
    strategy = HybridWindowStrategy(keep_messages=1, max_tokens=5000, tool_max_chars=0, hard_limit=10)
    messages: list[BaseMessage] = [HumanMessage("a", id="m1"), HumanMessage("b", id="m2")]

    assert await strategy.compact(messages, user_id=7) == []
    assert fake_store.upserts == []


@pytest.mark.asyncio
async def test_compact_forces_removal_above_hard_limit(fake_store: _FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """摘要连续失败且已超硬上限：强制删除窗口外消息，避免短期记忆无界增长。"""
    monkeypatch.setattr(window, "_build_summary_llm", _unavailable_llm)
    # 硬上限至少为 keep_messages + 1，这里取 2
    strategy = HybridWindowStrategy(keep_messages=1, max_tokens=5000, tool_max_chars=0, hard_limit=2)
    messages: list[BaseMessage] = [
        HumanMessage("a", id="m1"),
        HumanMessage("b", id="m2"),
        HumanMessage("c", id="m3"),
    ]

    removed = await strategy.compact(messages, user_id=7)

    assert [message.id for message in removed] == ["m1", "m2"]


@pytest.mark.asyncio
async def test_compact_does_nothing_when_within_window(fake_store: _FakeStore, fake_llm: _FakeLLM) -> None:
    """消息都在窗口内时不压缩，也不触碰记忆存储。"""
    strategy = HybridWindowStrategy(keep_messages=4, max_tokens=5000, tool_max_chars=0, hard_limit=10)
    messages: list[BaseMessage] = [HumanMessage("a", id="m1"), AIMessage("b", id="m2")]

    assert await strategy.compact(messages, user_id=7) == []
    assert fake_store.upserts == []
    assert fake_llm.prompts == []


@pytest.mark.asyncio
async def test_compact_survives_unavailable_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """记忆后端不可用时只降级保留消息，不应让整轮对话失败。"""
    monkeypatch.setattr(runtime, "get_memory_store", lambda: _FakeStore(available=False))
    strategy = HybridWindowStrategy(keep_messages=1, max_tokens=5000, tool_max_chars=0, hard_limit=10)
    messages: list[BaseMessage] = [HumanMessage("a", id="m1"), HumanMessage("b", id="m2")]

    assert await strategy.compact(messages, user_id=7) == []


@pytest.mark.asyncio
async def test_compact_skips_messages_without_id(fake_store: _FakeStore, fake_llm: _FakeLLM) -> None:
    """缺少 id 的消息无法生成 RemoveMessage（LangGraph 场景下 id 由框架补齐）。"""
    strategy = HybridWindowStrategy(keep_messages=1, max_tokens=5000, tool_max_chars=0, hard_limit=10)
    messages: list[BaseMessage] = [HumanMessage("无 id 的旧消息"), HumanMessage("新消息", id="m2")]

    assert await strategy.compact(messages, user_id=7) == []


@pytest.mark.asyncio
async def test_summary_compact_uses_count_window(fake_store: _FakeStore, fake_llm: _FakeLLM) -> None:
    """总结策略（非 hybrid）按条数压缩，回归确认重构未改变其行为。"""
    strategy = SummaryWindowStrategy(keep_messages=1, hard_limit=10)
    messages: list[BaseMessage] = [HumanMessage("a", id="m1"), HumanMessage("b", id="m2")]

    assert [message.id for message in await strategy.compact(messages, user_id=7)] == ["m1"]
    assert fake_store.profile is not None
    assert fake_store.profile.history_summary == "滚动摘要"
