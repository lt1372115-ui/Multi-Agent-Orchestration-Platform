from fastmcp.utilities.lifespan import combine_lifespans

from app.api import router
from app.logs.core.agents.a2a.server import a2a_lifespan, build_a2a_mounts
from app.logs.core.agents.orchestrator import (
    AnalystSubAgent,
    CustomerServiceSubAgent,
    DingTalkSubAgent,
    ECommerceSubAgent,
    QWeatherSubAgent,
)
from app.logs.core.config import settings
from app.logs.core.setup import create_application
from mcp_servers.qweather_mcp.server import mcp as qweather_mcp
from mcp_servers.task_mcp.server import mcp as taskmcp

app = create_application(router=router, settings=settings)

# 和风天气 MCP：挂载到 /qweather_mcp
qweather_app = qweather_mcp.http_app(path="/", transport="streamable-http")

# 任务管理 MCP：挂载到 /task-mcp
task_app = taskmcp.http_app(path="/", transport="streamable-http")

# A2A 服务：把五个子智能体作为「独立 A2A Agent」挂载到 /a2a/{name}，
# 每个 Agent 一张 Agent Card（能力发现）+ JSON-RPC 端点（调用）。
_a2a_agents = [
    QWeatherSubAgent(),
    DingTalkSubAgent(),
    ECommerceSubAgent(),
    CustomerServiceSubAgent(),
    AnalystSubAgent(),
]
_a2a_mounts = build_a2a_mounts(_a2a_agents, base_url=settings.A2A_PUBLIC_BASE_URL)

app.router.lifespan_context = combine_lifespans(
    app.router.lifespan_context,
    qweather_app.lifespan,
    task_app.lifespan,
    a2a_lifespan,
)
app.mount("/qweather_mcp", qweather_app)
app.mount("/task-mcp", task_app)
for _name, _a2a_app in _a2a_mounts.items():
    app.mount(f"/a2a/{_name}", _a2a_app)
