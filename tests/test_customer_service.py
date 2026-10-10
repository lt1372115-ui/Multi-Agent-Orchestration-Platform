"""客服智能体阶段 A（最小骨架）的冒烟测试。

不调用大模型、不依赖 Postgres / Redis：
- 路由已注册到 ``/api/v1/customer_service/chat``；
- 事件翻译层（``_translate``）能正确处理零工具纯聊天路径；
- 订单查询工具（``lookup_order``）已接入并可用。
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.logs.core.agents.customer_service import (
    after_sale as after_sale_module,
    order as order_module,
    tools as customer_service_tools,
)
from app.logs.core.agents.customer_service.agent import _thread_id, _translate
from app.main import app


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


async def _collect(sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    async def gen() -> AsyncIterator[dict[str, Any]]:
        for event in sequence:
            yield event

    return [event async for event in _translate(gen())]


def _of(events: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [event for event in events if event["type"] == event_type]


@pytest.mark.asyncio
async def test_translate_chitchat_without_tools() -> None:
    """零工具纯聊天：缓冲的文本应作为回答原样吐出，并产出唯一 done 事件。"""
    events = await _collect(
        [
            _model_start("m1"),
            _model_stream("m1", _Chunk("您好，请问有什么可以帮您？")),
            _model_end("m1"),
        ]
    )

    assert "".join(event["content"] for event in _of(events, "content")) == "您好，请问有什么可以帮您？"
    done = _of(events, "done")
    assert len(done) == 1
    assert done[0]["path"] == [{"id": "m1", "kind": "model", "label": "模型第 1 轮思考"}]


def test_lookup_order_tool_is_registered() -> None:
    """lookup_order / apply_return 工具已注册到客服智能体。"""
    names = [tool.name for tool in customer_service_tools.customer_service_tools]
    assert "lookup_order" in names
    assert "apply_return" in names


@pytest.mark.asyncio
async def test_builtin_order_source_lookup_found() -> None:
    """按订单号能查到已存在的订单。"""
    source = order_module.build_order_source()
    order = await source.lookup("SO20260901001")
    assert order is not None
    assert order.status == "已发货"
    assert "轻便透气跑步鞋" in order.to_text()


@pytest.mark.asyncio
async def test_builtin_order_source_lookup_missing() -> None:
    """查不存在的订单返回 None，且订单号大小写不敏感。"""
    source = order_module.build_order_source()
    assert await source.lookup("SO99999999999") is None
    assert await source.lookup("so20260901001") is not None


@pytest.mark.asyncio
async def test_lookup_order_tool_returns_text() -> None:
    """lookup_order 工具能返回订单文本，未找到时返回提示。"""
    from app.logs.core.agents.customer_service.tools import lookup_order

    result = await lookup_order.ainvoke({"order_id": "SO20260901001"})
    assert "已发货" in str(result)
    missing = await lookup_order.ainvoke({"order_id": "SO99999999999"})
    assert "未查询到订单" in str(missing)


def test_customer_service_route_is_registered() -> None:
    """路由应注册到 /api/v1/customer_service/chat。"""
    assert "/api/v1/customer_service/chat" in app.openapi()["paths"]


def test_thread_id_isolation() -> None:
    """短期记忆按 conversation_id 隔离，user_id 固定为 0。"""
    assert _thread_id("abc123") == "0:abc123"


@pytest.mark.asyncio
async def test_builtin_return_source_apply_found() -> None:
    """对已存在的订单提交退换货申请，返回待审核申请且订单号一致。"""
    source = after_sale_module.build_return_source()
    request = await source.apply("SO20260903003", "退货", "商品尺码不合适")
    assert request is not None
    assert request.order_id == "SO20260903003"
    assert request.action == "退货"
    assert request.status == "待审核"
    assert "申请单号" in request.to_text()


@pytest.mark.asyncio
async def test_builtin_return_source_apply_missing() -> None:
    """对不存在的订单提交退换货申请返回 None；非法类型回退为退货。"""
    source = after_sale_module.build_return_source()
    assert await source.apply("SO99999999999", "退货", "不喜欢") is None
    request = await source.apply("SO20260901001", "随便写", "不喜欢")
    assert request is not None
    assert request.action == "退货"


@pytest.mark.asyncio
async def test_apply_return_tool_returns_text() -> None:
    """apply_return 工具能返回申请文本，订单不存在时返回提示。"""
    from app.logs.core.agents.customer_service.tools import apply_return

    result = await apply_return.ainvoke({"order_id": "SO20260902002", "action": "换货", "reason": "质量问题"})
    assert "申请单号" in str(result)
    assert "换货" in str(result)
    missing = await apply_return.ainvoke({"order_id": "SO99999999999", "action": "退货", "reason": "不喜欢"})
    assert "未查询到订单" in str(missing)
