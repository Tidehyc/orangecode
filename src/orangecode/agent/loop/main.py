"""Agent Loop: 多轮思考与工具执行状态机。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from orangecode.agent.tools.base import ToolRegistry
from orangecode.context.assembler import ContextAssembler
from orangecode.providers.base import LLMProvider, TokenUsage, ToolCallRequest
from orangecode.spine.events import TextDelta, ToolEvent, ToolPhase, TurnEvent


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
        context_assembler: ContextAssembler | None = None,
        default_system_prompt: str | None = None,
        event_sink: Callable[[TurnEvent], Awaitable[None]] | None = None,
    ) -> None:
        self.provider = provider
        self.tool_registry = tool_registry or ToolRegistry()
        self.assembler = context_assembler or ContextAssembler()
        self.default_system_prompt = (
            default_system_prompt
            or "You are OrangeCode, a helpful and precise agent assistant."
        )
        self.event_sink = event_sink

    async def _execute_single_tool(self, tc: ToolCallRequest) -> dict[str, Any]:
        """执行单个工具调用并在任务取消时清理残留。"""
        logger.debug(f"Executing tool {tc.name} (call_id: {tc.id})")
        if self.event_sink:
            await self.event_sink(
                ToolEvent(
                    tool_name=tc.name,
                    phase=ToolPhase.START,
                    arguments=tc.arguments,
                )
            )

        try:
            result = await self.tool_registry.execute(tc.name, tc.arguments)
        except asyncio.CancelledError:
            logger.warning(f"In-flight tool execution '{tc.name}' was cancelled.")
            raise

        if self.event_sink:
            await self.event_sink(
                ToolEvent(
                    tool_name=tc.name,
                    phase=ToolPhase.COMPLETE,
                    arguments=tc.arguments,
                    result=str(result),
                    failed=getattr(result, "failed", False),
                )
            )

        return {
            "role": "tool",
            "tool_call_id": tc.id,
            "name": tc.name,
            "content": str(result),
        }

    async def _dispatch_tool_calls(self, tool_calls: list[ToolCallRequest]) -> list[dict[str, Any]]:
        """根据工具元能力声明，并发执行安全的只读操作，串行化写入操作，避免写冲突。"""
        if not tool_calls:
            return []

        def _is_safe(tc: ToolCallRequest) -> bool:
            tool_inst = self.tool_registry.get(tc.name)
            if not tool_inst:
                return False
            cap = getattr(tool_inst, "capability", None)
            return bool(getattr(cap, "concurrency_safe", False))

        # 将连续的并发安全工具切分为 batch，非安全工具作为单个任务串行执行
        results: list[dict[str, Any]] = []
        i = 0
        n = len(tool_calls)

        while i < n:
            tc = tool_calls[i]
            if _is_safe(tc):
                # 寻找连续的安全只读工具集合
                safe_batch = [tc]
                j = i + 1
                while j < n and _is_safe(tool_calls[j]):
                    safe_batch.append(tool_calls[j])
                    j += 1

                if len(safe_batch) > 1:
                    logger.info(f"Concurrent execution of {len(safe_batch)} safe read tools")
                    batch_res = await asyncio.gather(*[self._execute_single_tool(item) for item in safe_batch])
                    results.extend(batch_res)
                else:
                    res = await self._execute_single_tool(tc)
                    results.append(res)
                i = j
            else:
                # 非安全或写操作串行执行
                res = await self._execute_single_tool(tc)
                results.append(res)
                i += 1

        return results

    async def run(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[dict[str, Any]] | None = None,
        memories: list[str] | None = None,
        max_iterations: int = 20,
    ) -> AgentLoopOutcome:
        """启动 Agent 执行循环，直到生成最终回复或达到最大迭代轮次。"""
        # 1. 准备工具 Schema
        tools_schema = self.tool_registry.list_schemas()
        tools_param = tools_schema if tools_schema else None

        # 2. 上下文治理装配（Token 预算核算、工具输出压缩、历史原子裁剪）
        active_system_prompt = system_prompt or self.default_system_prompt
        messages, trim_outcome = self.assembler.assemble(
            system_prompt=active_system_prompt,
            history=history or [],
            current_prompt=prompt,
            memories=memories,
            tools=tools_param,
        )

        if trim_outcome.warnings:
            logger.info(f"Context governance applied: {trim_outcome.warnings}")

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

                # 执行工具调用：根据读写安全性并发执行只读安全工具，串行化写入工具
                tool_messages = await self._dispatch_tool_calls(response.tool_calls)
                messages.extend(tool_messages)

                # 继续下一轮循环，将工具结果喂给模型
                continue

            # 情况 B: 模型已输出最终文本，没有进一步工具调用需求
            final_text = response.content or ""
            if self.event_sink and final_text:
                await self.event_sink(TextDelta(delta=final_text))

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
