"""和风天气 MCP Server（FastMCP + Streamable HTTP）。

使用 FastMCP 高层封装，工具注册、参数校验、JSON-RPC 协议均由框架处理。
启动方式：

    uv run python src/mcp_servers/qweather_mcp/server.py
"""

from fastmcp import FastMCP

from app.logs.core.agents.qweather.client import (
    format_current_weather,
    get_current_weather,
    lookup_city,
)

mcp = FastMCP("qweather——mcp")


@mcp.tool
async def query_qweather_now(city: str) -> str:
    """查询指定城市的实时天气，返回天气状况、温度、体感温度、风力、湿度等信息。

    当用户询问某地当前天气，或需要根据当前天气决定出行、穿衣、是否带伞时使用。

    Args:
        city: 城市名，例如「北京」「杭州」。
    """
    location = await lookup_city(city)
    latitude = float(location["lat"])
    longitude = float(location["lon"])
    data = await get_current_weather(f"{latitude},{longitude}")
    return format_current_weather(data, city)
