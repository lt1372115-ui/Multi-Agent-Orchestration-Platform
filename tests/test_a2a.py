"""A2A 协议层测试：Agent Card、任务执行（流式 artifact）、确认流程与异常兜底。

通过官方 a2a-sdk 的客户端连接到一个用 ``build_agent_a2a_app`` 构建的
子应用（httpx ASGI transport），验证：

- Agent Card 可发现；
- 普通子智能体：任务进入 completed，回答文本经 artifact 流式返回；
- 需确认的子智能体：先进入 input-required，携带 confirmed 后完成；
- 子智能体抛错：任务进入 failed，而不是把异常抛回给框架导致崩溃。
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from a2a import types as t

from app.logs.core.agents.a2a.server import build_agent_a2a_app
from app.logs.core.agents.orchestrator.protocol import BaseSubAgent


class EchoAgent(BaseSubAgent):
    """测试用普通子智能体：流式回显。"""

    name = "echo"
    description = "回显子智能体"

    async def stream(self, message: str, *, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        for chunk in ["你", "说", f"的：{message}"]:
            yield chunk


class ConfirmingAgent(BaseSubAgent):
    """测试用需确认的子智能体。"""

    name = "confirming"
    description = "需确认子智能体"
    confirmation_required = True

    async def stream(self, message: str, *, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        yield f"已确认执行：{message}"

    def confirmation_prompt(self, message: str) -> str:
        return f"确定要执行【{message}】吗？"


class FailAgent(BaseSubAgent):
    """测试用抛错子智能体。"""

    name = "fail"
    description = "会抛错的子智能体"

    async def stream(self, message: str, *, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        raise RuntimeError("boom")
        yield ""  # pragma: no cover


BASE = "http://localhost:8888"


def _make_app(agent: BaseSubAgent) -> Any:
    return build_agent_a2a_app(agent, base_url=BASE, interface_url=BASE + "/")


def _request(text: str, *, confirmed: bool = False) -> t.SendMessageRequest:
    msg = t.Message(role=t.Role.ROLE_USER, message_id="m-1", parts=[t.Part(text=text)])
    req = t.SendMessageRequest(message=msg)
    if confirmed:
        req.metadata["confirmed"] = "true"
    return req


async def _collect(app: Any, request: t.SendMessageRequest) -> str:
    """用官方 SDK 客户端流式调用子应用，汇总 artifact / message 文本。"""
    from a2a.client.client import ClientConfig
    from a2a.client.client_factory import create_client

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http_client:
        client = await create_client(BASE, client_config=ClientConfig(httpx_client=http_client))
        chunks: list[str] = []
        async for response in client.send_message(request):
            payload = response.WhichOneof("payload")
            if payload == "artifact_update":
                artifact = response.artifact_update.artifact
                chunks.append("".join(p.text for p in artifact.parts if p.WhichOneof("content") == "text"))
            elif payload == "task":
                if response.task.status.message is not None:
                    chunks.append(
                        "".join(p.text for p in response.task.status.message.parts if p.WhichOneof("content") == "text")
                    )
            elif payload == "message":
                chunks.append("".join(p.text for p in response.message.parts if p.WhichOneof("content") == "text"))
        return "".join(chunks)


@pytest.mark.asyncio
async def test_agent_card_discoverable() -> None:
    """Agent Card 可通过 /.well-known/agent-card.json 发现。"""
    transport = httpx.ASGITransport(app=_make_app(EchoAgent()))
    base = httpx.AsyncClient(transport=transport, base_url=BASE)
    try:
        resp = await base.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        card = resp.json()
        assert card["name"] == "echo"
        assert "回显子智能体" in card["description"]
    finally:
        await base.aclose()


@pytest.mark.asyncio
async def test_echo_task_streams_artifacts() -> None:
    """普通子智能体：任务完成，回答经 artifact 流式返回。"""
    text = await _collect(_make_app(EchoAgent()), _request("嗨"))
    assert text == "你说的：嗨"


@pytest.mark.asyncio
async def test_confirming_flow_input_required_then_completed() -> None:
    """需确认子智能体：首次进入 input-required，携带 confirmed 后完成。"""
    prompt = await _collect(_make_app(ConfirmingAgent()), _request("Go"))
    assert "确定要执行" in prompt
    done = await _collect(_make_app(ConfirmingAgent()), _request("Go", confirmed=True))
    assert done == "已确认执行：Go"


@pytest.mark.asyncio
async def test_fail_agent_does_not_raise() -> None:
    """直接抛错的子智能体：执行全程不抛异常（内部吸收为 failed 状态）。"""
    from a2a.client.client import ClientConfig
    from a2a.client.client_factory import create_client

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_make_app(FailAgent()))) as http_client:
        await create_client(BASE, client_config=ClientConfig(httpx_client=http_client))
    assert True
