"""编排器引擎：基于 LangGraph 的 supervisor（监督者）模式。

把三个子智能体包装成「工具」交给监督者大模型，让它迭代式地决定每一步调谁、
拿到结果后再决定下一步，直到它认为可以给出最终回答。
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import SecretStr

from app.logs.core.agents.ecommerce.checkpointer import get_checkpointer
from app.logs.core.agents.ecommerce.session import new_conversation_id, thread_lock
from app.logs.core.agents.orchestrator.confirmation import ConfirmationRequired, has_pending
from app.logs.core.agents.orchestrator.protocol import BaseSubAgent
from app.logs.core.config import settings

logger = logging.getLogger(__name__)

_SUPERVISOR_SYSTEM_PREFIX = (
    "你是智能助手编排者（supervisor）。你可以直接回答用户，也可以把任务交给以下子智能体处理。"
    "你可以按需调用一个或多个子智能体，也可以不调用。子智能体的回答会返回给你，"
    "你可以据此继续调用其他子智能体，或直接给出最终回答。最终回答请用简洁的中文。\n"
    "如果某个子智能体的操作结果提示『等待用户确认』，说明该操作已被搁置等待用户决定；"
    "除非用户明确要求执行，否则不要再次调用该子智能体。\n"
    "子智能体列表：\n"
)


class SupervisorState(TypedDict, total=False):
    """supervisor 图状态：对话消息、透传给子智能体的上下文与待确认请求。"""

    messages: Annotated[list[BaseMessage], add_messages]
    context: dict[str, Any] | None
    pending_confirm: list[dict[str, Any]] | None


_registry: dict[str, BaseSubAgent] = {}
_graph: Any | None = None
_llm: ChatOpenAI | None = None
# 图构建锁：首个并发请求同时进入时只编译一次，避免重复编译与重复初始化 Checkpointer
_graph_lock = asyncio.Lock()


def register_agent(agent: BaseSubAgent) -> None:
    """向编排器注册一个子智能体（同名覆盖），并使缓存图失效。"""
    global _graph
    _registry[agent.name] = agent
    _graph = None


def clear_agents() -> None:
    """清空已注册的子智能体（主要用于测试隔离），并使缓存图失效。"""
    global _graph
    _registry.clear()
    _graph = None


def get_agents() -> list[BaseSubAgent]:
    """返回当前已注册的子智能体，按注册顺序。"""
    return list(_registry.values())


def get_agent(name: str) -> BaseSubAgent | None:
    """按名称取子智能体，未注册时返回 None。"""
    return _registry.get(name)


def build_supervisor_system_prompt() -> str:
    """构造 supervisor 系统提示词，附带各子智能体的能力描述。"""
    lines = [_SUPERVISOR_SYSTEM_PREFIX]
    lines.extend(f"- {agent.name}：{agent.description}" for agent in get_agents())
    return "\n".join(lines)


def _get_llm() -> ChatOpenAI:
    """获取大模型客户端单例（流式）。"""
    global _llm
    if _llm is None:
        if not settings.DEEPSEEK_API_KEY or not settings.DEEPSEEK_MODEL or not settings.DEEPSEEK_BASE_URL:
            raise RuntimeError("DeepSeek 配置不完整，请检查 DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_BASE_URL")
        _llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            api_key=SecretStr(settings.DEEPSEEK_API_KEY),
            base_url=settings.DEEPSEEK_BASE_URL,
            temperature=0.7,
            streaming=True,
            timeout=60,
        )
    return _llm


def _make_agent_tool(agent: BaseSubAgent) -> Any:
    """为子智能体生成工具 schema（仅供大模型识别，实际执行在工具节点）。"""

    @tool(agent.name, description=agent.description)
    async def call(message: str) -> str:
        """调用子智能体处理消息，返回其回答文本。"""
        return ""

    return call


def _build_agent_tools() -> list[Any]:
    """按当前注册表生成 supervisor 可见的子智能体工具列表。"""
    return [_make_agent_tool(agent) for agent in get_agents()]


def _sanitize_history(messages: list[Any]) -> list[Any]:
    """清洗发给 LLM 的历史：剔除没有 tool 响应跟随的孤儿 assistant(tool_calls) 消息。

    checkpointer 历史可能残留异常中断 / 旧版本产生的残缺序列（assistant 带
    ``tool_calls`` 却缺少对应 ``tool`` 响应），会把下一轮 LLM 调用打回 400
    （``insufficient tool messages following tool_calls message``）；发送前统一剔除。
    """
    responded = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    clean: list[Any] = []
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            ids = {tc["id"] for tc in m.tool_calls}
            if ids and not ids.issubset(responded):
                continue
        clean.append(m)
    return clean


def _route_after_supervisor(state: SupervisorState) -> str:
    """supervisor 节点之后：有工具调用则执行工具，否则结束。"""
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    if getattr(last, "tool_calls", None):
        return "tools"
    return "end"


def _route_after_tools(state: SupervisorState) -> str:
    """工具节点之后：有待确认操作则结束本轮（交给上层做确认交互），否则回到 supervisor。"""
    return "end" if state.get("pending_confirm") else "supervisor"


def build_graph(checkpointer: Any | None = None) -> Any:
    """构建 supervisor 图：supervisor 节点与工具节点循环。

    ``checkpointer`` 传入后按 ``thread_id`` 保存会话历史，实现编排器短期记忆。
    """
    tools = _build_agent_tools()

    async def supervisor_node(state: SupervisorState) -> dict[str, Any]:
        """supervisor 节点：大模型决定调用子智能体或直接回答。"""
        system = SystemMessage(content=build_supervisor_system_prompt())
        response = await _get_llm().bind_tools(tools).ainvoke([system, *_sanitize_history(state.get("messages", []))])
        return {"messages": [response]}

    async def tools_node(state: SupervisorState) -> dict[str, Any]:
        """工具节点：按大模型的调用名执行对应子智能体。

        需要确认的子智能体不在此执行：先写入占位 tool 响应，保证消息序列始终完整
        （assistant 的 ``tool_calls`` 之后必须紧跟对应的 ``tool`` 响应，否则残缺历史
        会在下一轮被 LLM 以 400 拒绝），再把待确认信息放进 ``pending_confirm``，
        由路由直接结束本轮，上层据此发起确认交互。
        """
        messages = state.get("messages", [])
        last = messages[-1] if messages else None
        context = state.get("context")
        tool_messages: list[ToolMessage] = []
        pending_confirm: list[dict[str, Any]] = []
        for call in getattr(last, "tool_calls", None) or []:
            name = call["name"]
            agent = get_agent(name)
            message = str((call.get("args") or {}).get("message", ""))
            if agent is None:
                result = f"未知子智能体：{name}"
            elif agent.needs_confirmation(context):
                result = "[该操作需要用户确认，已搁置等待用户决定；请勿再次发起，等待用户在界面上确认或取消]"
                # 同一会话已有未决确认时不重复弹确认框（由 supervisor 据占位响应直接回答）
                if not has_pending(context):
                    pending_confirm.append({"agent_name": name, "message": message, "context": context})
            else:
                try:
                    result = await agent.run(message, context=context)
                except Exception as exc:
                    logger.warning("子智能体 %s 执行失败: %s", name, exc)
                    result = f"[{name} 暂时无法回答]"
            tool_messages.append(ToolMessage(content=result, name=name, tool_call_id=call["id"]))
        return {"messages": tool_messages, "pending_confirm": pending_confirm or None}

    builder = StateGraph(SupervisorState)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("tools", tools_node)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", _route_after_supervisor, {"tools": "tools", "end": END})
    builder.add_conditional_edges("tools", _route_after_tools, {"supervisor": "supervisor", "end": END})
    return builder.compile(checkpointer=checkpointer)


async def get_graph() -> Any:
    """获取编译好的 supervisor 图单例，挂载短期记忆 Checkpointer。

    图缓存失效（注册表变化）时重建，Checkpointer 复用全局单例（进程内或 Postgres）。
    """
    global _graph
    if _graph is None:
        async with _graph_lock:
            if _graph is None:
                _graph = build_graph(checkpointer=await get_checkpointer())
    return _graph


def _thread_id_from_context(context: dict[str, Any] | None) -> str:
    """从透传上下文解析短期记忆的 ``thread_id``（``user_id:conversation_id``）。

    未提供 ``conversation_id`` 时按轮新建会话（等价于无记忆兜底）。
    """
    ctx = context or {}
    user_id = int(ctx.get("user_id", 0) or 0)
    conversation_id = ctx.get("conversation_id") or new_conversation_id()
    return f"{user_id}:{conversation_id}"


def _raise_if_pending_confirm(
    pending_confirm: list[dict[str, Any]] | None,
    context: dict[str, Any] | None,
) -> None:
    """有待确认操作时抛 ``ConfirmationRequired``，把确认交互交还上层（API/前端）。

    图内不再抛异常（异常中断会留下残缺历史触发 LLM 400），改在图跑完后统一检查。
    """
    if not pending_confirm:
        return
    first = pending_confirm[0]
    agent = get_agent(first["agent_name"])
    prompt = agent.confirmation_prompt(first["message"]) if agent else f"即将执行操作：{first['message']}。"
    raise ConfirmationRequired(
        agent_name=first["agent_name"],
        message=first["message"],
        context=first.get("context") or context,
        prompt=prompt,
    )


def _extract_final_answer(messages: list[Any]) -> str:
    """从消息列表逆序取最后一条无工具调用的 AI 回答文本。"""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = message.content
            if isinstance(content, str) and content:
                return content
    return ""


async def invoke(question: str, *, context: dict[str, Any] | None = None) -> str:
    """非流式执行 supervisor 图，返回最终回答文本（供测试与内部使用）。

    短期记忆按 ``user_id:conversation_id`` 隔离，同会话的多轮对话会累积历史。
    """
    graph = await get_graph()
    thread_id = _thread_id_from_context(context)
    config = {"configurable": {"thread_id": thread_id}}
    async with thread_lock(thread_id):
        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": question}], "context": context, "pending_confirm": None},
            config=config,
        )
    _raise_if_pending_confirm(result.get("pending_confirm"), context)
    return _extract_final_answer(result.get("messages", []))


async def stream_answer(
    question: str,
    *,
    context: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """编排入口：运行 supervisor 图，对最终回答做增量流式输出。

    中间的工具调用与过渡文本会被丢弃，仅保留大模型最终给出的回答并逐段产出。
    短期记忆按 ``user_id:conversation_id`` 隔离，同会话的多轮对话会累积历史。
    """
    graph = await get_graph()
    thread_id = _thread_id_from_context(context)
    config = {"configurable": {"thread_id": thread_id}}
    buffer: list[str] = []

    async with thread_lock(thread_id):
        async for event in graph.astream_events(
            {"messages": [{"role": "user", "content": question}], "context": context, "pending_confirm": None},
            config=config,
            version="v2",
        ):
            kind = event["event"]
            node = event.get("metadata", {}).get("langgraph_node")
            if kind == "on_chat_model_stream" and node == "supervisor":
                content = event["data"]["chunk"].content
                if isinstance(content, str) and content:
                    buffer.append(content)
            elif kind == "on_chat_model_end" and node == "supervisor":
                output = event["data"]["output"]
                if getattr(output, "tool_calls", None):
                    # 该次输出带工具调用，属过渡输出，丢弃
                    buffer.clear()
                else:
                    # 最终回答，逐段产出
                    for text in buffer:
                        yield text
                    buffer.clear()

        # 有待确认操作时抛信号（图内不中断，跑完后统一检查，保证历史完整）
        state = await graph.aget_state(config)
        _raise_if_pending_confirm((state.values or {}).get("pending_confirm"), context)

        for text in buffer:
            yield text
