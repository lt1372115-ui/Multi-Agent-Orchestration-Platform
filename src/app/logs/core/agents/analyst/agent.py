"""分析智能体：由大模型生成运营日报等数据分析结果。

对外只暴露 :func:`stream_events`，它把 LangChain 内部细碎的运行事件翻译成前端
可以直接消费的扁平事件流：链路节点（模型第几轮思考、调用了哪个工具）与回答文本
分开推送，前端因此既能实时显示调用链路，也能在回答结束后保留一条完整的链路摘要。

已接入运营日报生成工具与短期记忆（按会话累积历史）。
"""

from collections.abc import AsyncGenerator, AsyncIterator
from time import perf_counter
from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.logs.core.agents.analyst.prompts import SYSTEM_PROMPT
from app.logs.core.agents.analyst.tools import analyst_tools
from app.logs.core.agents.ecommerce.checkpointer import get_checkpointer
from app.logs.core.agents.ecommerce.session import thread_lock
from app.logs.core.config import settings

# 工具名 -> 中文动作，未知工具回退为工具名本身
_TOOL_LABELS: dict[str, str] = {"generate_daily_report": "生成运营日报"}

# 单条工具原始返回最多回传多少字符，避免 SSE 帧过大
_PREVIEW_LIMIT = 800


def _build_agent(checkpointer: Any) -> Any:
    model = settings.DEEPSEEK_MODEL
    api_key = settings.DEEPSEEK_API_KEY
    base_url = settings.DEEPSEEK_BASE_URL
    if not model or not api_key or not base_url:
        raise RuntimeError("DeepSeek 配置不完整，请检查 DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_BASE_URL")

    llm = ChatOpenAI(
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
        temperature=0.7,
        streaming=True,
        timeout=60,
    )
    return create_agent(llm, analyst_tools, system_prompt=SYSTEM_PROMPT, checkpointer=checkpointer)


_agent: Any | None = None


async def get_agent() -> Any:
    """惰性创建并缓存 Agent 实例，挂载短期记忆 Checkpointer。"""
    global _agent
    if _agent is None:
        _agent = _build_agent(checkpointer=await get_checkpointer())
    return _agent


# ---------------- 事件翻译辅助 ----------------


def _text_of(value: Any, limit: int = _PREVIEW_LIMIT) -> str:
    """尽力把工具返回值转成可读文本，超长时截断。"""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (list, tuple)):
        text = "\n".join(_text_of(item, limit) for item in value)
    else:
        content = getattr(value, "content", None)
        text = _text_of(content, limit) if content is not None else str(value)
    text = text.strip()
    return text if len(text) <= limit else f"{text[:limit]}…"


def _summarize(text: str, limit: int = 46) -> str:
    """从工具返回结果里抽出最有信息量的一两行，压成单行摘要。"""
    picked: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "：" in line:
            line = line.split("：", 1)[1].strip()
        if line:
            picked.append(line)
        if len(picked) == 2:
            break
    joined = " · ".join(picked)
    return joined if len(joined) <= limit else f"{joined[:limit]}…"


def _tool_label(name: str, args: Any) -> str:
    """由工具名与入参生成中文动作描述，例如「生成运营日报「2026-10-08」」。"""
    params = args if isinstance(args, dict) else {}
    target = str(params.get("date") or "").strip()
    base = _TOOL_LABELS.get(name, name)
    return f"{base}「{target}」" if target else base


# ---------------- 事件翻译 ----------------


async def _translate(events: AsyncIterator[dict[str, Any]]) -> AsyncGenerator[dict[str, Any]]:
    """把 LangChain ``astream_events`` 的事件翻译成前端事件。

    产出的事件类型：

    - ``{"type": "step", "phase": "start", ...}``：链路节点开始。``kind`` 为
      ``model``（模型某一轮思考）或 ``tool``（工具调用）；``id`` 取 LangChain 的
      ``run_id``，前端据此把同一节点的 start / end 合并为一条记录。
    - ``{"type": "step", "phase": "end", ...}``：链路节点结束，附带 ``status``、
      ``elapsed_ms``；工具节点还带 ``summary`` 与 ``preview``（原始返回）。
    - ``{"type": "content", "content": str}``：最终回答的文本片段。
    - ``{"type": "done", "elapsed_ms": int, "path": list}``：本次运行结束，
      ``path`` 是按执行顺序排列的链路节点摘要。

    工具调用前模型可能输出的思考文本会被丢弃，只保留最终回答；若整轮没有调用任何
    工具（闲聊场景），缓冲的文本会作为回答原样吐出。
    """
    started = perf_counter()
    turns = 0
    tool_seen = False
    buffer: list[str] = []
    running_tools: dict[str, float] = {}
    last_model_run = ""
    model_started = started
    path: list[dict[str, Any]] = []

    async for event in events:
        kind = event.get("event")
        run_id = str(event.get("run_id") or "")
        now = perf_counter()

        if kind == "on_chat_model_start":
            turns += 1
            last_model_run = run_id
            model_started = now
            label = f"模型第 {turns} 轮思考"
            path.append({"id": run_id, "kind": "model", "label": label})
            yield {"type": "step", "phase": "start", "id": run_id, "kind": "model", "turn": turns, "label": label}
            continue

        if kind == "on_chat_model_end":
            yield {
                "type": "step",
                "phase": "end",
                "id": run_id,
                "kind": "model",
                "status": "ok",
                "elapsed_ms": int((now - model_started) * 1000),
            }
            continue

        if kind == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            content = chunk if isinstance(chunk, str) else getattr(chunk, "content", None)
            if not isinstance(content, str) or not content:
                continue
            if tool_seen:
                yield {"type": "content", "content": content}
            else:
                buffer.append(content)
            continue

        if kind == "on_tool_start":
            tool_seen = True
            buffer.clear()
            name = str(event.get("name") or "")
            args = event.get("data", {}).get("input") or {}
            label = _tool_label(name, args)
            running_tools[run_id] = now
            path.append({"id": run_id, "kind": "tool", "name": name, "label": label})
            yield {
                "type": "step",
                "phase": "start",
                "id": run_id,
                "kind": "tool",
                "name": name,
                "label": label,
                "args": args,
                "parent": last_model_run,
            }
            continue

        if kind == "on_tool_end":
            result = _text_of(event.get("data", {}).get("output"))
            yield {
                "type": "step",
                "phase": "end",
                "id": run_id,
                "kind": "tool",
                "status": "ok",
                "elapsed_ms": int((now - running_tools.pop(run_id, now)) * 1000),
                "summary": _summarize(result),
                "preview": result,
            }
            continue

        if kind == "on_tool_error":
            error = event.get("data", {}).get("error")
            yield {
                "type": "step",
                "phase": "end",
                "id": run_id,
                "kind": "tool",
                "status": "error",
                "elapsed_ms": int((now - running_tools.pop(run_id, now)) * 1000),
                "summary": str(error or "工具调用失败")[:120],
                "preview": "",
            }
            continue

    if not tool_seen:
        for text in buffer:
            yield {"type": "content", "content": text}

    yield {"type": "done", "elapsed_ms": int((perf_counter() - started) * 1000), "path": path}


def _thread_id(conversation_id: str) -> str:
    """分析智能体未接入鉴权，user_id 固定为 0，短期记忆按 conversation_id 隔离。"""
    return f"0:{conversation_id}"


async def stream_events(question: str, conversation_id: str) -> AsyncGenerator[dict[str, Any]]:
    """流式产出 Agent 事件（事件结构见 :func:`_translate`）。

    ``conversation_id`` 由路由层生成，作为短期记忆的 ``thread_id`` 隔离维度；
    同一会话的多轮对话会累积历史。
    """
    agent = await get_agent()
    thread_id = _thread_id(conversation_id)
    config = {"configurable": {"thread_id": thread_id}}
    async with thread_lock(thread_id):
        stream = agent.astream_events(
            {"messages": [{"role": "user", "content": question}]},
            config=config,
            version="v2",
        )
        async for event in _translate(stream):
            yield event


async def stream_answer(question: str, conversation_id: str) -> AsyncGenerator[str]:
    """流式输出纯文本回答（仅保留 ``content`` 事件）。"""
    async for event in stream_events(question, conversation_id):
        if event["type"] == "content":
            yield event["content"]
