"""和风天气路由：实况、未来预报、出行建议与智能体问答。"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.logs.core.agents.qweather import agent as qweather_agent, client as qweather
from app.logs.core.deepseek import stream_chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qweather", tags=["天气管理"])


@router.get("/weather/now")
async def weather_now(location: str) -> dict[str, Any]:
    """查询指定经纬度位置（纬度,经度）的实时天气。"""
    data = await qweather.get_current_weather(location)
    return {"location": location, "weather": data}


@router.get("/weather/10d")
async def weather_10d(city: str, days: Annotated[int, Query(ge=1, le=10)] = 10) -> dict[str, Any]:
    """根据城市名查询未来 N 天（默认 10 天）的每日天气预报。"""
    location = await qweather.lookup_city(city)
    latitude = float(location["lat"])
    longitude = float(location["lon"])
    forecast = await qweather.get_daily_forecast(latitude, longitude, days=days)
    return {
        "city": {
            "name": location.get("name"),
            "id": location.get("id"),
            "adm1": location.get("adm1"),
            "adm2": location.get("adm2"),
            "country": location.get("country"),
            "latitude": latitude,
            "longitude": longitude,
        },
        "days": forecast.get("days") or [],
    }


"""出行建议生成：把天气信息交给大模型生成出行建议。"""


async def generate_travel_advice(weather_text: str) -> str:
    """根据天气信息调用 DeepSeek 生成中文出行建议。

    Args:
        weather_text: 天气工具返回的文本描述。

    Returns:
        大模型生成的出行建议文本。
    """
    system_prompt = (
        "你是一个贴心的出行助手。请根据用户提供的天气信息，"
        "用简洁、实用的中文给出出行建议，可涵盖穿衣、防晒/防雨、带伞、"
        "出行方式、户外活动注意事项等，并结合体感温度给出提醒。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"以下是当前天气信息：\n{weather_text}\n\n请给我出行建议。"},
    ]

    return "".join([chunk async for chunk in stream_chat(messages)])


@router.get("/travel-advice")
async def travel_advice(location: str) -> dict[str, Any]:
    """查询实时天气并一次性返回出行建议文本。"""
    data = await qweather.get_current_weather(location)
    weather_text = qweather.format_current_weather(data, location)
    advice = await generate_travel_advice(weather_text)
    return {"location": location, "weather": weather_text, "advice": advice}


class ChatRequest(BaseModel):
    """智能体问答请求体。"""

    question: str


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """智能体问答（SSE 流式）：模型自行调用天气工具后给出出行建议，并回传调用链路。

    每条事件都以 ``data: `` 开头，内容为 JSON：

    - ``{"type": "step", "phase": "start", ...}`` 链路节点开始。``kind`` 为 ``model``
      （模型某一轮思考）或 ``tool``（工具调用）；``id`` 用于把同一节点的 start / end
      配对。工具节点额外带 ``name``、``label``（中文动作，如「查询「杭州」的实时天气」）、
      ``args``（入参）与 ``parent``（触发它的模型节点 id）。
    - ``{"type": "step", "phase": "end", ...}`` 链路节点结束，带 ``status`` 与
      ``elapsed_ms``；工具节点还带 ``summary``（一行摘要）与 ``preview``（原始返回）。
    - ``{"type": "content", "content": "..."}`` 回答文本片段。
    - ``{"type": "error", "message": "..."}`` 生成过程失败。
    - ``{"type": "done", "elapsed_ms": int, "path": [...]}`` 本次回答结束，
      ``path`` 是按顺序排列的链路节点摘要，本次流中保证只出现一次。
    """

    async def event_stream() -> AsyncGenerator[str]:
        finished = False
        try:
            async for event in qweather_agent.stream_events(req.question):
                finished = finished or event["type"] == "done"
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("智能体回答失败")
            payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        if not finished:
            # 异常或中断时补一个终止标记，保证前端总能收到 done
            yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
