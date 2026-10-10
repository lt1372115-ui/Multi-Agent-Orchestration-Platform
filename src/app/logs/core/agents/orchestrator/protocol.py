"""编排器的子智能体调用协议。

编排器只依赖本协议，不直接依赖具体智能体；后续把「进程内实现」替换为
「A2A 远程实现」时，编排器代码无需改动。
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class BaseSubAgent(ABC):
    """子智能体的统一调用契约。

    每个子智能体（qweather / dingtalk / ecommerce）提供进程内实现；
    后续 A2A 阶段再为各智能体提供远程客户端实现，两者遵循同一契约。
    """

    name: str = ""
    description: str = ""
    # 是否需要用户确认后才执行（钉钉写操作等场景为 True）
    confirmation_required: bool = False

    @abstractmethod
    def stream(self, message: str, *, context: dict[str, Any] | None = None) -> AsyncIterator[str]:
        """逐段流式产出该智能体对 ``message`` 的最终回答文本。"""
        raise NotImplementedError

    async def run(self, message: str, *, context: dict[str, Any] | None = None) -> str:
        """非流式调用：收集 ``stream`` 的全部输出并拼接返回。"""
        return "".join([chunk async for chunk in self.stream(message, context=context)])

    def confirmation_prompt(self, message: str) -> str:
        """生成待确认提示（仅 ``confirmation_required=True`` 时使用）。"""
        return f"即将执行操作：{message}。请回复「确认」继续，或「取消」放弃。"

    def needs_confirmation(self, context: dict[str, Any] | None) -> bool:
        """是否需要用户确认：需确认且上下文中尚未携带确认决定。"""
        return self.confirmation_required and not bool((context or {}).get("confirmed"))
