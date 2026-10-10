"""电商导购智能体：``create_agent`` + 三层记忆的短期记忆窗口管理。

本模块把 :mod:`app.logs.core.agents.window` 的窗口策略接到 ``create_agent`` 的三个时机上：

- ``@dynamic_prompt``：用 ``prompts.build_memory_context`` 把用户画像（含 ``compact``
  写入的 ``history_summary``）与召回记忆注入系统提示词，保证被压缩掉的旧对话仍能被
  模型看到，并带上历史数据的防护说明。
- ``@wrap_model_call``（trim）：每次调用模型前裁剪上下文——工具输出截断、只保留最近几轮
  原文、按 token 预算兜底；只影响这一次注入的内容，不改动短期记忆。
- ``@after_agent``（compact）：一轮对话结束后，把窗口外的旧消息滚动摘要进
  ``UserProfile.history_summary``，再用 ``RemoveMessage`` 经 ``add_messages`` reducer
  真正从短期记忆中移除，避免 checkpoint 无界增长。

短期记忆存放在 LangGraph Checkpointer（``ECOMMERCE_CHECKPOINT_BACKEND``），
长期记忆存放在 ``MemoryStore``（``ECOMMERCE_MEMORY_BACKEND``）。
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRequest,
    ModelResponse,
    Runtime,
    after_agent,
    dynamic_prompt,
    wrap_model_call,
)
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from app.logs.core.agents import runtime as agents_runtime
from app.logs.core.agents.ecommerce.prompts import SYSTEM_PROMPT, build_memory_context
from app.logs.core.agents.ecommerce.session import thread_lock
from app.logs.core.agents.ecommerce.state import AgentState
from app.logs.core.agents.ecommerce.tools import ecommerce_tools
from app.logs.core.config import settings

logger = logging.getLogger(__name__)

_ModelHandler = Callable[[ModelRequest], Awaitable[ModelResponse]]


def _build_model() -> ChatOpenAI:
    """创建导购智能体使用的大模型客户端（DeepSeek，OpenAI 兼容接口）。"""
    if not settings.DEEPSEEK_API_KEY or not settings.DEEPSEEK_MODEL or not settings.DEEPSEEK_BASE_URL:
        raise RuntimeError("DeepSeek 配置不完整，请检查 DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_BASE_URL")

    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key=SecretStr(settings.DEEPSEEK_API_KEY),
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=0.7,
        streaming=True,
        timeout=60,
    )


def _build_checkpointer() -> BaseCheckpointSaver:
    """按 ``ECOMMERCE_CHECKPOINT_BACKEND`` 创建短期记忆 Checkpointer。"""
    backend = (settings.ECOMMERCE_CHECKPOINT_BACKEND or "memory").strip().lower()
    if backend == "memory":
        return InMemorySaver()

    # postgres 需要 langgraph-checkpoint-postgres（AsyncPostgresSaver），当前依赖中未包含
    raise NotImplementedError(
        f"ECOMMERCE_CHECKPOINT_BACKEND={backend} 尚未接入：请先安装 langgraph-checkpoint-postgres，"
        "再在 _build_checkpointer() 中返回 AsyncPostgresSaver"
    )


@dynamic_prompt
async def inject_long_term_memory(request: ModelRequest) -> str:
    """把用户画像与召回记忆注入系统提示词。

    ``compact`` 会把窗口外的旧对话压进 ``UserProfile.history_summary``；
    这里把它连同长期记忆一起注入，「压缩」才不等于「丢失」。两者都是用户历史数据，
    统一交给 :func:`prompts.build_memory_context` 做清洗、裁剪与注入防护。
    """
    prompt: str = SYSTEM_PROMPT
    state: dict[str, Any] = dict(request.state)
    user_id = state.get("user_id")
    if user_id is None:
        return prompt

    memories: list[dict[str, Any]] = list(state.get("recalled_memories") or [])
    try:
        profile = await agents_runtime.get_memory_store().get_profile(user_id)
    except Exception as exc:
        logger.warning("读取用户画像失败，本次忽略长期记忆: %s", exc)
        profile = None

    if profile is None and not memories:
        return prompt

    query = next(
        (str(message.content) for message in reversed(request.messages) if message.type == "human"),
        "",
    )
    context = build_memory_context(profile.to_dict() if profile else None, memories, query)
    return f"{prompt}\n\n{context}"


@wrap_model_call
async def trim_context(request: ModelRequest, handler: _ModelHandler) -> ModelResponse:
    """调用模型前裁剪上下文：工具输出截断 + 最近几轮原文 + token 预算兜底。"""
    trimmed = agents_runtime.get_window_strategy().trim(list(request.messages))
    if len(trimmed) != len(request.messages):
        logger.debug("上下文裁剪：%d -> %d 条消息", len(request.messages), len(trimmed))
    # 窗口策略按 BaseMessage 处理（需兼容 RemoveMessage 等控制消息），而
    # ModelRequest.override 的形参收窄为 AnyMessage 联合；运行时传入的是同一批消息对象。
    return await handler(request.override(messages=trimmed))  # type: ignore[arg-type]


# 本项目用自定义 AgentState 承载 user_id / 召回记忆 / 画像等额外字段，
# 与 langchain 泛型中间件声明的 StateT 上界在类型层面不兼容，运行时由 LangGraph 直接消费。
@after_agent  # type: ignore[type-var]
async def compact_history(state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
    """一轮对话结束后压缩短期记忆。

    窗口外的旧消息滚动摘要进长期画像后，用 ``RemoveMessage`` 交回状态，
    由 ``add_messages`` reducer 真正从短期记忆中删除。
    """
    user_id = state.get("user_id")
    if user_id is None:
        logger.debug("state 缺少 user_id，跳过短期记忆压缩")
        return None

    removals = await agents_runtime.get_window_strategy().compact(list(state["messages"]), user_id)
    if not removals:
        return None

    logger.info("短期记忆压缩完成：移除 %d 条旧消息（user_id=%s）", len(removals), user_id)
    return {"messages": removals}


def _build_agent() -> Any:
    """创建导购智能体：DeepSeek 模型 + 商品检索工具 + 三层记忆中间件。"""
    return create_agent(
        _build_model(),
        ecommerce_tools,
        middleware=[inject_long_term_memory, trim_context, compact_history],  # type: ignore[list-item]
        state_schema=AgentState,  # type: ignore[arg-type]
        checkpointer=_build_checkpointer(),
    )


_agent: Any | None = None


def get_agent() -> Any:
    """惰性创建并缓存导购智能体实例。"""
    global _agent
    if _agent is None:
        _agent = _build_agent()
    return _agent


async def ask(question: str, *, user_id: int, thread_id: str) -> str:
    """单轮问答：把用户问题交给智能体并返回最终回答文本。

    Args:
        question: 用户问题。
        user_id: 用户 ID，短期记忆压缩按用户归档画像。
        thread_id: 会话 ID，用于区分不同会话的短期记忆。
    """
    # 与会话流式接口共用同一把会话级锁，避免同一 thread_id 的并发读改写竞态
    async with thread_lock(thread_id):
        result = await get_agent().ainvoke(
            {"messages": [HumanMessage(question)], "user_id": user_id},
            config={"configurable": {"thread_id": thread_id}},
        )
    for message in reversed(result.get("messages") or []):
        if getattr(message, "type", "") == "ai" and not getattr(message, "tool_calls", None):
            return str(message.content)
    return ""
