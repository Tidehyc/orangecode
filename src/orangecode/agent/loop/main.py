"""Agent Loop: 多轮思考与工具执行状态机。"""

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from orangecode.agent.tools.base import ToolRegistry
from orangecode.providers.base import LLMProvider, TokenUsage


@dataclass
class AgentLoopOutcome:
    """Agent Loop 单次任务执行完成的最终产物。"""

    final_content: str
    messages: list[dict[str, Any]]
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    iterations: int = 0
    success: bool = True
    error_message: str | None = None


class AgentLoop:
    """Agent 核心执行循环状态机。"""

    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry | None = None,
        default_system_prompt: str | None = None,
    ) -> None:
        self.provider = provider
        self.tool_registry = tool_registry or ToolRegistry()
        self.default_system_prompt = (
            default_system_prompt
            or "You are OrangeCode, a helpful and precise agent assistant."
        )

    async def run(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[dict[str, Any]] | None = None,
        max_iterations: int = 20,
    ) -> AgentLoopOutcome:
        """启动 Agent 执行循环，直到生成最终回复或达到最大迭代轮次。"""
        # 1. 组装初始消息
        messages: list[dict[str, Any]] = []

        active_system_prompt = system_prompt or self.default_system_prompt
        if active_system_prompt:
            messages.append({"role": "system", "content": active_system_prompt})

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": prompt})

        # 2. 准备工具 Schema
        tools_schema = self.tool_registry.list_schemas()
        tools_param = tools_schema if tools_schema else None

        total_usage = TokenUsage()
        iteration = 0

        # 3. 循环推进：LLM 思考 -> 工具分发 -> 观察反馈
        while iteration < max_iterations:
            iteration += 1
            logger.info(f"Agent Loop Iteration {iteration}/{max_iterations}")

            # 调用模型
            response = await self.provider.chat_complete(
                messages=messages,
                tools=tools_param,
            )

            # 累计 Token
            total_usage.prompt_tokens += response.usage.prompt_tokens
            total_usage.completion_tokens += response.usage.completion_tokens
            total_usage.total_tokens += response.usage.total_tokens

            # 情况 A: 模型要求调用工具
            if response.has_tool_calls:
                logger.info(
                    f"LLM requested {len(response.tool_calls)} tool call(s): "
                    f"{[tc.name for tc in response.tool_calls]}"
                )

                # 将 Assistant 的工具调用意图存入消息流
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [tc.to_openai_tool_call() for tc in response.tool_calls],
                }
                messages.append(assistant_msg)

                # 执行工具调用并记录观察结果
                for tc in response.tool_calls:
                    logger.debug(f"Executing tool {tc.name} (call_id: {tc.id})")
                    result = await self.tool_registry.execute(tc.name, tc.arguments)

                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": str(result),
                    }
                    messages.append(tool_msg)

                # 继续下一轮循环，将工具结果喂给模型
                continue

            # 情况 B: 模型已输出最终文本，没有进一步工具调用需求
            final_text = response.content or ""
            messages.append({"role": "assistant", "content": final_text})
            logger.info(f"Agent Loop completed successfully in {iteration} iteration(s).")
            return AgentLoopOutcome(
                final_content=final_text,
                messages=messages,
                total_usage=total_usage,
                iterations=iteration,
                success=True,
            )

        # 达到最大迭代次数依然没有完结
        warn_msg = f"Agent Loop reached maximum iterations ({max_iterations}) without concluding."
        logger.warning(warn_msg)
        return AgentLoopOutcome(
            final_content="[Terminated: Reached maximum iterations threshold.]",
            messages=messages,
            total_usage=total_usage,
            iterations=iteration,
            success=False,
            error_message=warn_msg,
        )
