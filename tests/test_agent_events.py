"""智能体事件翻译层（``_translate``）的单元测试。

不调用大模型、不依赖 Postgres / Redis：直接回放构造好的 astream_events 事件序列，
校验工具调用链路、摘要、错误处理与终端事件的产出。
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.logs.core.agents.qweather.agent import _translate

WEATHER_TEXT = (
    "地点：杭州\n天气：晴\n温度：26°C\n体感温度：27°C\n相对湿度：58%\n"
    "风向：东南风\n风力等级：2\n风速：3.4m/s\n阵风风速：6.1m/s"
)

FORECAST_TEXT = "地点：杭州\n未来 10 天每日天气预报：\n2026-09-21：白天 晴，夜间 多云，气温 20~28°C，白天风力 东风 2 级"


class _Chunk:
    """模拟 LangChain 的消息分片（带 content 属性）。"""

    def __init__(self, content: str) -> None:
        self.content = content


def _model_start(run_id: str) -> dict[str, Any]:
    return {"event": "on_chat_model_start", "run_id": run_id, "name": "ChatOpenAI"}


def _model_end(run_id: str) -> dict[str, Any]:
    return {"event": "on_chat_model_end", "run_id": run_id, "data": {}}


def _model_stream(run_id: str, content: Any) -> dict[str, Any]:
    return {"event": "on_chat_model_stream", "run_id": run_id, "data": {"chunk": content}}


def _tool_start(run_id: str, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"event": "on_tool_start", "run_id": run_id, "name": name, "data": {"input": args or {}}}


def _tool_end(run_id: str, name: str, output: str) -> dict[str, Any]:
    return {"event": "on_tool_end", "run_id": run_id, "name": name, "data": {"output": output}}


def _weather_sequence() -> list[dict[str, Any]]:
    """典型链路：模型第 1 轮决定查天气 → 调工具 → 模型第 2 轮给出回答。"""
    return [
        _model_start("m1"),
        _model_stream("m1", _Chunk("我先查一下。")),
        _model_end("m1"),
        _tool_start("t1", "query_qweather_now", {"city": "杭州"}),
        _tool_end("t1", "query_qweather_now", WEATHER_TEXT),
        _model_start("m2"),
        _model_stream("m2", _Chunk("杭州现在晴，26°C，")),
        _model_stream("m2", _Chunk("体感 27°C，适合出门。")),
        _model_end("m2"),
    ]


async def _collect(sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    async def gen() -> AsyncIterator[dict[str, Any]]:
        for event in sequence:
            yield event

    return [event async for event in _translate(gen())]


def _of(events: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [event for event in events if event["type"] == event_type]


@pytest.mark.asyncio
async def test_tool_step_exposes_label_args_and_summary() -> None:
    steps = _of(await _collect(_weather_sequence()), "step")
    tool_start = next(step for step in steps if step["kind"] == "tool" and step["phase"] == "start")
    tool_end = next(step for step in steps if step["kind"] == "tool" and step["phase"] == "end")

    assert tool_start["label"] == "查询「杭州」的实时天气"
    assert tool_start["args"] == {"city": "杭州"}
    assert tool_start["parent"] == "m1"
    assert tool_end["status"] == "ok"
    assert tool_end["summary"] == "晴 · 26°C"
    assert "地点：杭州" in tool_end["preview"]


@pytest.mark.asyncio
async def test_model_turns_are_reported_in_order() -> None:
    steps = _of(await _collect(_weather_sequence()), "step")
    model_starts = [step for step in steps if step["kind"] == "model" and step["phase"] == "start"]

    assert [step["turn"] for step in model_starts] == [1, 2]
    assert [step["label"] for step in model_starts] == ["模型第 1 轮思考", "模型第 2 轮思考"]
    # 每个模型节点的 start / end 必须成对出现，前端才能正确收尾
    for step in model_starts:
        assert any(item["id"] == step["id"] and item["kind"] == "model" and item["phase"] == "end" for item in steps)


@pytest.mark.asyncio
async def test_answer_text_keeps_only_post_tool_output() -> None:
    events = await _collect(_weather_sequence())
    answer = "".join(event["content"] for event in _of(events, "content"))

    assert answer == "杭州现在晴，26°C，体感 27°C，适合出门。"
    assert "我先查一下" not in answer


@pytest.mark.asyncio
async def test_done_is_emitted_once_with_full_path() -> None:
    events = await _collect(_weather_sequence())
    done = _of(events, "done")

    assert len(done) == 1
    assert [node["label"] for node in done[0]["path"]] == [
        "模型第 1 轮思考",
        "查询「杭州」的实时天气",
        "模型第 2 轮思考",
    ]


@pytest.mark.asyncio
async def test_chitchat_without_tools_keeps_model_text() -> None:
    events = await _collect([_model_start("m1"), _model_stream("m1", _Chunk("你好")), _model_end("m1")])

    assert "".join(event["content"] for event in _of(events, "content")) == "你好"
    assert _of(events, "done")[0]["path"] == [{"id": "m1", "kind": "model", "label": "模型第 1 轮思考"}]


@pytest.mark.asyncio
async def test_forecast_tool_label_includes_days() -> None:
    events = await _collect(
        [
            _model_start("m1"),
            _tool_start("t1", "query_qweather_forecast", {"city": "杭州", "days": 10}),
            _tool_end("t1", "query_qweather_forecast", FORECAST_TEXT),
        ]
    )
    tool_start = next(step for step in _of(events, "step") if step["kind"] == "tool")
    tool_end = next(step for step in _of(events, "step") if step["kind"] == "tool" and step["phase"] == "end")

    assert tool_start["label"] == "查询「杭州」未来 10 天的天气"
    assert tool_end["summary"] == "白天 晴，夜间 多云，气温 20~28°C，白天风力 东风 2 级"


@pytest.mark.asyncio
async def test_tool_error_is_reported() -> None:
    events = await _collect(
        [
            _model_start("m1"),
            _tool_start("t1", "query_qweather_now"),
            {"event": "on_tool_error", "run_id": "t1", "data": {"error": "和风天气请求失败: HTTP 401"}},
        ]
    )
    tool_end = next(step for step in _of(events, "step") if step["kind"] == "tool" and step["phase"] == "end")

    assert tool_end["status"] == "error"
    assert "401" in tool_end["summary"]


@pytest.mark.asyncio
async def test_plain_string_chunk_is_tolerated() -> None:
    """LangChain 若回传裸字符串分片，不应该让整条流崩掉。"""
    events = await _collect([_model_start("m1"), _model_stream("m1", "纯文本分片"), _model_end("m1")])

    assert "".join(event["content"] for event in _of(events, "content")) == "纯文本分片"
