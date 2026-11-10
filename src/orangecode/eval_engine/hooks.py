"""Agent 生命周期执行钩子与审计审计系统。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class AgentHook:
    """Agent 运行生命周期拦截与监控基类。"""

    async def before_iteration(self, iteration: int, messages: list[dict[str, Any]]) -> None:
        """在每一轮思考调用大模型前触发。"""
        pass

    async def after_iteration(self, iteration: int, outcome_text: str | None, messages: list[dict[str, Any]]) -> None:
        """在模型完成单轮推理后触发。"""
        pass

    async def on_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        failed: bool,
    ) -> None:
        """在工具执行完成并返回观察结果时触发。"""
        pass


@dataclass
class ToolAuditRecord:
    tool_name: str
    arguments: dict[str, Any]
    result: str
    failed: bool
    timestamp: datetime = field(default_factory=datetime.now)


class ToolAuditHook(AgentHook):
    """记录 Agent 执行期间所有工具调用的审计跟踪器。"""

    def __init__(self) -> None:
        self.records: list[ToolAuditRecord] = []

    async def on_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        failed: bool,
    ) -> None:
        self.records.append(
            ToolAuditRecord(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                failed=failed,
            )
        )

    def summary(self) -> dict[str, Any]:
        total = len(self.records)
        failed_count = sum(1 for r in self.records if r.failed)
        return {
            "total_calls": total,
            "failed_calls": failed_count,
            "success_rate": (total - failed_count) / total if total > 0 else 1.0,
            "tools_used": list({r.tool_name for r in self.records}),
        }
