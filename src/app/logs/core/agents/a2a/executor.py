"""A2A 执行器：把子智能体包装成官方 a2a-sdk 的 AgentExecutor。

对应「第四章 A2A 协议」文档第 3~4 步：采用「长任务 + 流式 artifact」工作流，
回答用 Task + 逐段 Artifact 推送，而不是一次性返回一条 Message。子智能体中途
抛错时任务进入 ``failed`` 而非卡在 ``working``；若子智能体声明需要确认
（``confirmation_required``），则先进入 ``input-required`` 等待用户确认。
"""

import asyncio
import logging
from uuid import uuid4

from a2a import types
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater

from app.logs.core.agents.orchestrator.protocol import BaseSubAgent

logger = logging.getLogger(__name__)


class SubAgentExecutor(AgentExecutor):
    """把一个子智能体包装成 A2A 协议的 AgentExecutor。

    采用 A2A 的「长任务 + 流式 artifact」工作流：先发初始 Task，再逐段
    ``add_artifact`` 流式推送回答，最后进入 completed。若子智能体声明需要
    确认（``confirmation_required``），则先进入 ``input-required`` 等待用户确认。
    """

    def __init__(self, agent: BaseSubAgent) -> None:
        self._agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """执行子智能体：流式产出 artifact，必要时先请求确认。"""
        updater = TaskUpdater(event_queue, context.task_id or "", context.context_id or "")
        text = self._request_text(context)

        # 两种「已确认」：本服务端自身的 input-required 恢复；或编排器已确认后透传的 confirmed 标记
        confirmed = self._is_confirmed(context) or bool(context.metadata.get("confirmed"))

        # 所有路径都先登记一个初始 Task（SDK 要求：后续状态更新事件之前必须有 Task 事件）
        initial = types.Task(
            id=context.task_id,
            context_id=context.context_id,
            status=types.TaskStatus(state=types.TaskState.TASK_STATE_SUBMITTED),
        )
        await event_queue.enqueue_event(initial)

        # 需要确认且尚未确认：进入 input-required，用户确认后框架会再次调用本方法
        if self._agent.confirmation_required and not confirmed:
            prompt = self._agent.confirmation_prompt(text)
            initial.status.state = types.TaskState.TASK_STATE_INPUT_REQUIRED
            initial.status.message.CopyFrom(
                types.Message(
                    role=types.Role.ROLE_AGENT,
                    message_id=uuid4().hex,
                    parts=[types.Part(text=prompt)],
                )
            )
            initial.metadata["original_request"] = text
            await event_queue.enqueue_event(initial)
            return

        # 进入 working，随后逐段 append 到同一个 artifact
        await updater.start_work()

        artifact_id = uuid4().hex
        first = True
        try:
            async for chunk in self._agent.stream(text):
                await updater.add_artifact(
                    parts=[types.Part(text=chunk)],
                    artifact_id=artifact_id,
                    append=not first,
                )
                first = False
        except asyncio.CancelledError:
            # 取消交由框架处理（框架会另行调用 cancel()）
            raise
        except Exception as exc:
            # 子智能体执行异常：把任务置为 failed，避免卡在 working 非终态
            logger.exception("子智能体 %s 执行失败", self._agent.name)
            await self._mark_failed(updater, exc)
            return
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """取消进行中的任务。"""
        updater = TaskUpdater(event_queue, context.task_id or "", context.context_id or "")
        await updater.cancel()

    @staticmethod
    def _is_confirmed(context: RequestContext) -> bool:
        """判断本次调用是否是「确认恢复」：任务此前处于 input-required。"""
        current = context.current_task
        return current is not None and current.status.state == types.TaskState.TASK_STATE_INPUT_REQUIRED

    def _request_text(self, context: RequestContext) -> str:
        """取本次要执行的请求文本：确认恢复时从任务 metadata 取原始请求。"""
        current = context.current_task
        if self._is_confirmed(context) and current is not None:
            metadata = current.metadata
            if "original_request" in metadata:
                return str(metadata["original_request"])
        return context.get_user_input()

    @staticmethod
    async def _mark_failed(updater: TaskUpdater, exc: Exception) -> None:
        """把任务标记为 failed，附带简洁的错误信息（不泄露堆栈）。"""
        message = types.Message(
            role=types.Role.ROLE_AGENT,
            message_id=uuid4().hex,
            parts=[types.Part(text=f"执行失败：{exc}")],
        )
        try:
            await updater.failed(message=message)
        except Exception:
            # 任务可能已被并发推进到其它终态，忽略二次写入失败
            logger.exception("标记任务失败时出错")
