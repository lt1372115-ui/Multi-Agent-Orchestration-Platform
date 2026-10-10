"""流式对话接口：逐 token 产出最终回答文本。"""

from collections.abc import AsyncGenerator

from app.logs.core.agents.ecommerce.graph import get_graph
from app.logs.core.agents.ecommerce.session import new_conversation_id, thread_lock


async def stream_chat(user_id: int, message: str, conversation_id: str | None = None) -> AsyncGenerator[str]:
    """流式对话：逐 token 产出最终回答文本。

    只保留 ``answer`` 节点在工具调用之后生成的回答文本；工具调用前的思考文本
    与记忆提取（``memory_write`` 节点）的输出都会被过滤。会话隔离语义与
    :func:`service.chat` 一致，``conversation_id`` 为空时自动新建会话。
    """
    conversation_id = conversation_id or new_conversation_id()
    thread_id = f"{user_id}:{conversation_id}"
    graph = await get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    tool_seen = False
    buffer: list[str] = []

    async with thread_lock(thread_id):
        async for event in graph.astream_events(
            {"messages": [{"role": "user", "content": message}], "user_id": user_id},
            config=config,
            version="v2",
        ):
            kind = event.get("event")
            if kind == "on_tool_start":
                tool_seen = True
                buffer.clear()
                continue
            if kind != "on_chat_model_stream":
                continue
            if event.get("metadata", {}).get("langgraph_node") != "answer":
                continue
            content = event["data"]["chunk"].content
            if isinstance(content, str) and content:
                if tool_seen:
                    yield content
                else:
                    buffer.append(content)

    # 未调用工具时，answer 只生成一次，缓冲的即是最终回答
    if not tool_seen:
        for text in buffer:
            yield text
