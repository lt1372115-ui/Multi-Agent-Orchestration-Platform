"""分析智能体的 LangChain 工具封装，供 Agent 调用。"""

from langchain_core.tools import tool

from app.logs.core.agents.analyst.report import DailyReport, build_report_source


@tool
async def generate_daily_report(date: str) -> str:
    """生成指定日期的运营日报（订单量、GMV、用户增长、转化率等核心指标）。

    当用户要求生成运营日报、分析当日/昨日经营情况、查看核心经营指标时使用。

    Args:
        date: 日期，格式 YYYY-MM-DD，例如「2026-10-08」。用户说「今天」「昨天」时需换算成具体日期。
    """
    report: DailyReport | None = await build_report_source().generate(date)
    if report is None:
        return f"暂无「{date}」的运营数据，请核对日期后重试。"
    return str(report.to_text())


analyst_tools = [generate_daily_report]
