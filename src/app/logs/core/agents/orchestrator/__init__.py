"""编排器包：单入口多智能体编排（LangGraph supervisor 模式）。

包被 import 时按 ``ORCHESTRATOR_SUBAGENT_TRANSPORT`` 注册五个子智能体
（qweather / dingtalk / ecommerce / customer_service / analyst）：``inprocess``
用进程内适配器（默认），``a2a`` 用 ``A2ASubAgent`` 远程客户端。之后可随时通过
:func:`register_agent` 增删。
"""

from app.logs.core.agents.orchestrator.analyst_adapter import AnalystSubAgent
from app.logs.core.agents.orchestrator.confirmation import ConfirmationRequired, pop_pending, store_pending
from app.logs.core.agents.orchestrator.customer_service_adapter import CustomerServiceSubAgent
from app.logs.core.agents.orchestrator.dingtalk_adapter import DingTalkSubAgent
from app.logs.core.agents.orchestrator.ecommerce_adapter import ECommerceSubAgent
from app.logs.core.agents.orchestrator.engine import (
    build_graph,
    build_supervisor_system_prompt,
    clear_agents,
    get_agent,
    get_agents,
    get_graph,
    invoke,
    register_agent,
    stream_answer,
)
from app.logs.core.agents.orchestrator.protocol import BaseSubAgent
from app.logs.core.agents.orchestrator.qweather_adapter import QWeatherSubAgent
from app.logs.core.config import settings


def _register_defaults() -> None:
    """按配置注册默认的五个子智能体。"""
    if settings.ORCHESTRATOR_SUBAGENT_TRANSPORT == "a2a":
        from app.logs.core.agents.a2a import A2ASubAgent

        base = settings.A2A_PUBLIC_BASE_URL.rstrip("/")
        register_agent(
            A2ASubAgent(
                name="qweather",
                description="天气出行：实时天气、未来预报、穿衣与出行建议。",
                url=f"{base}/a2a/qweather",
            )
        )
        register_agent(
            A2ASubAgent(
                name="dingtalk",
                description="钉钉办公助手：通讯录搜索、日历日程、待办、消息与 DING、日志、考勤等办公操作。",
                url=f"{base}/a2a/dingtalk",
                confirmation_required=True,
            )
        )
        register_agent(
            A2ASubAgent(
                name="ecommerce",
                description="电商导购：商品推荐、选品与购物问题，记住偏好。",
                url=f"{base}/a2a/ecommerce",
            )
        )
        register_agent(
            A2ASubAgent(
                name="customer_service",
                description="客服助手：订单查询（状态、物流、退款进度）、常见问题解答与售后咨询。",
                url=f"{base}/a2a/customer_service",
            )
        )
        register_agent(
            A2ASubAgent(
                name="analyst",
                description="运营分析助手：生成运营日报，分析订单量、销售额、用户增长、转化率等核心经营指标。",
                url=f"{base}/a2a/analyst",
            )
        )
    else:
        register_agent(QWeatherSubAgent())
        register_agent(DingTalkSubAgent())
        register_agent(ECommerceSubAgent())
        register_agent(CustomerServiceSubAgent())
        register_agent(AnalystSubAgent())


_register_defaults()

__all__ = [
    "AnalystSubAgent",
    "BaseSubAgent",
    "ConfirmationRequired",
    "CustomerServiceSubAgent",
    "DingTalkSubAgent",
    "ECommerceSubAgent",
    "QWeatherSubAgent",
    "build_graph",
    "build_supervisor_system_prompt",
    "clear_agents",
    "get_agent",
    "get_agents",
    "get_graph",
    "invoke",
    "pop_pending",
    "register_agent",
    "store_pending",
    "stream_answer",
]
