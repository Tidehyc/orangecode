"""Turn 请求对象、归属来源与忙碌策略定义。"""

import asyncio
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Origin(StrEnum):
    """请求来源，决定并发池配额与安全边界。"""

    USER = "user"          # 真实交互用户，享有最高调度优先权
    CRON = "cron"          # 后台定时触发任务
    SUBAGENT = "subagent"  # 子 Agent 递归调用或结果回传


class BusyPolicy(StrEnum):
    """同一会话（Lane）正在执行任务时，新请求的排队与抢占策略。"""

    APPEND = "append"        # 排到队尾，顺序等待
    INTERRUPT = "interrupt"  # 立即取消当前执行的 Turn，抢占队首执行
    INJECT = "inject"        # 尝试在工具执行轮次间隙合并注入


@dataclass(frozen=True)
class TurnRequest:
    """提交给 Spine 调度的单次完整 Turn 请求。"""

    prompt: str
    conversation_id: str
    origin: Origin = Origin.USER
    busy_policy: BusyPolicy = BusyPolicy.APPEND
    turn_id: str = field(default_factory=lambda: f"turn_{uuid.uuid4().hex[:8]}")
    metadata: dict[str, Any] = field(default_factory=dict)


class TurnHandle:
    """提交任务后返回的控制句柄。"""

    def __init__(
        self,
        request: TurnRequest,
        future: asyncio.Future,
        cancel_fn: Any,
    ) -> None:
        self.request = request
        self.future = future
        self._cancel_fn = cancel_fn

    @property
    def turn_id(self) -> str:
        return self.request.turn_id

    @property
    def conversation_id(self) -> str:
        return self.request.conversation_id

    def cancel(self) -> bool:
        """请求取消当前 Turn。"""
        return self._cancel_fn(self.future)

    async def wait(self) -> Any:
        """等待该 Turn 执行结束并获取结果。"""
        return await self.future
