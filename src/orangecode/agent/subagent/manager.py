"""管理后台 Subagent 的隔离创建、资源限流与执行状态机。"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loguru import logger

from orangecode.agent.loop import AgentLoop
from orangecode.agent.tools.base import Tool, ToolRegistry, ToolResult
from orangecode.agent.tools.file_search import FindTool, GrepTool
from orangecode.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from orangecode.agent.tools.web import WebFetchTool
from orangecode.providers.base import LLMProvider


class SubagentStatus(StrEnum):
    """Subagent 终态标记。"""

    COMPLETED = "completed"
    FAILED = "failed"
    EXHAUSTED = "exhausted"

    @property
    def failed(self) -> bool:
        return self is not SubagentStatus.COMPLETED


@dataclass(frozen=True)
class SubagentOutcome:
    """Subagent 执行产物。"""

    status: SubagentStatus
    result: str

    @property
    def failed(self) -> bool:
        return self.status.failed


class SubagentManager:
    """管理并发 Subagent 派发、频率防抖与隔离执行。"""

    def __init__(
        self,
        provider: LLMProvider,
        max_concurrent: int = 4,
        max_spawns_per_hour: int = 50,
    ) -> None:
        self.provider = provider
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_spawns_per_hour = max_spawns_per_hour
        # 记录 session_key -> deque[timestamp]
        self._spawn_history: dict[str, deque[float]] = {}

    def _check_rate_limit(self, session_key: str) -> bool:
        now = time.time()
        window_start = now - 3600.0
        history = self._spawn_history.setdefault(session_key, deque())

        # 清除 1 小时前的旧记录
        while history and history[0] < window_start:
            history.popleft()

        if len(history) >= self._max_spawns_per_hour:
            return False

        history.append(now)
        return True

    def build_child_registry(self) -> ToolRegistry:
        """为子智能体构建专用的工具注册表（严禁挂载 SpawnTool，彻底杜绝递归分叉炸弹）。"""
        registry = ToolRegistry()
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(EditFileTool())
        registry.register(ListDirTool())
        registry.register(FindTool())
        registry.register(GrepTool())
        registry.register(WebFetchTool())
        return registry

    async def spawn(
        self,
        task: str,
        label: str = "subtask",
        session_key: str = "default",
        max_iterations: int = 15,
    ) -> SubagentOutcome:
        """派发并等待一个独立的 Subagent 完成指定任务。"""
        if not self._check_rate_limit(session_key):
            warn_msg = f"Spawn rate limit exceeded ({self._max_spawns_per_hour}/hour) for session '{session_key}'."
            logger.warning(warn_msg)
            return SubagentOutcome(status=SubagentStatus.FAILED, result=warn_msg)

        async with self._semaphore:
            logger.info(f"Spawning Subagent [{label}] for session {session_key}: {task[:80]}...")
            child_registry = self.build_child_registry()

            child_system_prompt = (
                f"You are a specialized subagent assigned to execute an independent task: '{label}'.\n"
                "Focus purely on fulfilling the user's objective using your available tools.\n"
                "Provide a concise, direct, and conclusive summary of your findings or results."
            )

            child_loop = AgentLoop(
                provider=self.provider,
                tool_registry=child_registry,
                default_system_prompt=child_system_prompt,
            )

            try:
                outcome = await child_loop.run(
                    prompt=task,
                    max_iterations=max_iterations,
                )

                if outcome.success:
                    return SubagentOutcome(
                        status=SubagentStatus.COMPLETED,
                        result=outcome.final_content,
                    )
                return SubagentOutcome(
                    status=SubagentStatus.EXHAUSTED,
                    result=outcome.final_content or (outcome.error_message or "Subagent reached iteration limit."),
                )
            except Exception as e:
                logger.exception(f"Subagent [{label}] failed with exception: {e}")
                return SubagentOutcome(
                    status=SubagentStatus.FAILED,
                    result=f"Subagent execution failed: {type(e).__name__}: {e}",
                )


class SpawnTool(Tool):
    """允许主 Agent 派发子 Agent 协同工作的专用工具。"""

    name = "spawn_subagent"
    description = (
        "Spawn an isolated, background subagent to execute a dedicated subtask and return its result. "
        "Useful for deep codebase search, extensive investigation, or modular problem solving without polluting main context."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Clear, complete description of the subtask for the subagent to execute.",
            },
            "label": {
                "type": "string",
                "description": "Short 2-4 word identifier label for this subagent task.",
            },
        },
        "required": ["task"],
    }
    timeout_seconds = 300.0

    def __init__(self, manager: SubagentManager) -> None:
        self.manager = manager

    async def execute(self, task: str, label: str = "subtask", **kwargs: Any) -> ToolResult:
        outcome = await self.manager.spawn(task=task, label=label)
        if outcome.failed:
            return ToolResult(f"Subagent [{label}] failed: {outcome.result}", failed=True)
        return ToolResult(
            f"Subagent [{label}] completed successfully.\n\nResult:\n{outcome.result}",
            failed=False,
        )
