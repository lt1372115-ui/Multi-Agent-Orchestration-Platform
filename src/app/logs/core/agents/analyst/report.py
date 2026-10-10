"""分析智能体的运营日报数据源抽象层：内置演示数据，后续可替换为真实数据仓库。

业务代码只依赖 :class:`ReportSource` 协议，切换日报数据来源只需修改
``ANALYST_REPORT_SOURCE`` 配置：当前仅 ``builtin``（内置演示数据），
真实数据仓库（http / postgres / clickhouse）可在此按协议新增后端。
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from app.logs.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DailyReport:
    """一天的运营日报。"""

    date: str
    order_count: int
    revenue: float
    new_users: int
    active_users: int
    conversion_rate: float
    refund_count: int
    top_products: list[str]

    def to_text(self) -> str:
        """转为适合大模型阅读的日报文本。"""
        return (
            f"# 运营日报（{self.date}）\n"
            f"- 订单量：{self.order_count} 单\n"
            f"- 销售额（GMV）：{self.revenue:,.2f} 元\n"
            f"- 新增用户：{self.new_users} 人\n"
            f"- 活跃用户：{self.active_users} 人\n"
            f"- 转化率：{self.conversion_rate:.1f}%\n"
            f"- 退款订单：{self.refund_count} 单\n"
            f"- 热销商品 Top：{'、'.join(self.top_products)}"
        )


@runtime_checkable
class ReportSource(Protocol):
    """运营日报数据的统一接口。新来源只需实现本协议并在 :func:`build_report_source` 注册。"""

    async def generate(self, date: str) -> DailyReport | None:
        """生成指定日期（YYYY-MM-DD）的运营日报，无数据返回 None。"""
        ...


# 近三天的演示指标，按「今天／昨天／前天」顺序填充
_DEMO_METRICS: list[tuple[int, float, int, int, float, int, list[str]]] = [
    (1280, 186500.0, 342, 5120, 4.8, 35, ["轻便透气跑步鞋", "智能运动手表", "运动水杯"]),
    (1105, 158000.0, 289, 4870, 4.3, 41, ["智能运动手表", "轻便透气跑步鞋", "瑜伽垫"]),
    (960, 121000.0, 251, 4350, 4.1, 28, ["运动水杯", "轻便透气跑步鞋", "跳绳"]),
]


class BuiltinReportSource(ReportSource):
    """基于内置演示数据的运营日报，动态生成近三天的数据（日期不过时）。"""

    async def generate(self, date: str) -> DailyReport | None:
        target = date.strip()
        # 演示指标按「本地自然日」生成：先取 UTC 当前时刻，再转成本地时区（保证 tz-aware）
        today = datetime.now(UTC).astimezone().date()
        for offset, metrics in enumerate(_DEMO_METRICS):
            day = today - timedelta(days=offset)
            if day.isoformat() == target:
                orders, revenue, new_users, active, conv, refund, top = metrics
                return DailyReport(
                    date=day.isoformat(),
                    order_count=orders,
                    revenue=revenue,
                    new_users=new_users,
                    active_users=active,
                    conversion_rate=conv,
                    refund_count=refund,
                    top_products=top,
                )
        return None


def build_report_source(source: str | None = None) -> ReportSource:
    """根据配置创建运营日报数据源。当前仅支持内置演示数据。"""
    source = source or settings.ANALYST_REPORT_SOURCE
    if source != "builtin":
        raise NotImplementedError(f"ANALYST_REPORT_SOURCE={source} 尚未实现，请改用 builtin 或接入真实数据仓库")
    logger.info("运营日报数据源：builtin（内置演示数据）")
    return BuiltinReportSource()
