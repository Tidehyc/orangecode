"""人工介入与询问确认工具：支持提问、选项选择与高危操作审批。"""

from collections.abc import Awaitable, Callable
from typing import Any

from orangecode.agent.tools.base import Tool, ToolResult
from orangecode.agent.tools.execution import ToolCapability, ToolEffect


class AskUserTool(Tool):
    """向人类用户提出问题、请求补充信息或申请操作审批。"""

    name = "ask_user"
    description = (
        "Ask the user a question to clarify ambiguous instructions, request missing information, "
        "or seek approval for potentially dangerous operations."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question or confirmation message to present to the user.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of choices for the user to select from.",
            },
        },
        "required": ["question"],
    }
    # 显式声明 blocking_interaction=True，调度器不得对其包装通用硬超时
    blocking_interaction: bool = True
    capability = ToolCapability(effect=ToolEffect.EXTERNAL, concurrency_safe=False)

    def __init__(
        self,
        input_handler: Callable[[str, list[str] | None], Awaitable[str]] | None = None,
    ) -> None:
        self.input_handler = input_handler

    async def execute(
        self,
        question: str,
        options: list[str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if self.input_handler:
            answer = await self.input_handler(question, options)
            return ToolResult(answer, failed=False)

        # 默认无回调时的回退输出
        opts_str = f" Options: {options}" if options else ""
        return ToolResult(
            f"[User interaction requested: '{question}'{opts_str} - Auto-acknowledged in non-interactive environment.]",
            failed=False,
        )
