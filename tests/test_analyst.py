"""分析智能体的冒烟测试。

不调用大模型、不依赖 Postgres / Redis：
- 路由已注册到 ``/api/v1/analyst/chat``；
- 运营日报数据源（``BuiltinReportSource``）能按日期生成演示日报、无数据返回 None；
- 运营日报工具（``generate_daily_report``）已接入并可用；
- 编排器适配器元信息正确。
"""

from datetime import UTC, datetime

import pytest

from app.logs.core.agents.analyst import report as report_module, tools as analyst_tools
from app.logs.core.agents.analyst.agent import _thread_id
from app.main import app


def _today() -> str:
    return datetime.now(UTC).astimezone().date().isoformat()


@pytest.mark.asyncio
async def test_builtin_report_source_generate_found() -> None:
    """近三天（含今天）能生成运营日报，文本包含核心指标。"""
    source = report_module.build_report_source()
    report = await source.generate(_today())
    assert report is not None
    assert report.date == _today()
    assert "订单量" in report.to_text()
    assert "销售额" in report.to_text()


@pytest.mark.asyncio
async def test_builtin_report_source_generate_missing() -> None:
    """远古日期无数据，返回 None。"""
    source = report_module.build_report_source()
    assert await source.generate("2000-01-01") is None


def test_generate_daily_report_tool_is_registered() -> None:
    """generate_daily_report 工具已注册到分析智能体。"""
    names = [tool.name for tool in analyst_tools.analyst_tools]
    assert "generate_daily_report" in names


@pytest.mark.asyncio
async def test_generate_daily_report_tool_returns_text() -> None:
    """工具能返回日报文本，无数据时返回提示。"""
    from app.logs.core.agents.analyst.tools import generate_daily_report

    result = await generate_daily_report.ainvoke({"date": _today()})
    assert "运营日报" in str(result)
    missing = await generate_daily_report.ainvoke({"date": "2000-01-01"})
    assert "暂无" in str(missing)


def test_analyst_route_is_registered() -> None:
    """路由应注册到 /api/v1/analyst/chat。"""
    assert "/api/v1/analyst/chat" in app.openapi()["paths"]


def test_thread_id_isolation() -> None:
    """短期记忆按 conversation_id 隔离，user_id 固定为 0。"""
    assert _thread_id("abc123") == "0:abc123"


def test_analyst_adapter_metadata() -> None:
    """分析适配器的 name / description / confirmation_required 正确。"""
    from app.logs.core.agents.orchestrator.analyst_adapter import AnalystSubAgent

    agent = AnalystSubAgent()
    assert agent.name == "analyst"
    assert "运营日报" in agent.description
    assert agent.confirmation_required is False
