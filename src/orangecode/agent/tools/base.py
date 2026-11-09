"""定义 Agent Tool 的抽象契约、执行结果与注册中心。"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from loguru import logger


class ToolResult(str):
    """带明确执行状态的 Tool 返回结果。"""

    failed: bool

    def __new__(cls, value: object = "", *, failed: bool = False):
        result = super().__new__(cls, str(value))
        result.failed = failed
        return result


class Tool(ABC):
    """所有 Agent Tool 的基类。"""

    name: str
    description: str
    parameters: dict[str, Any]
    timeout_seconds: float = 30.0

    def to_schema(self) -> dict[str, Any]:
        """导出为 OpenAI Function Calling 规范的 JSON Schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """异步执行该工具的具体逻辑。"""
        raise NotImplementedError


class ToolRegistry:
    """工具注册与统一分发中心。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具。"""
        if tool.name in self._tools:
            logger.warning(f"Overwriting already registered tool: {tool.name}")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Tool | None:
        """按名称获取工具。"""
        return self._tools.get(name)

    def list_schemas(self) -> list[dict[str, Any]]:
        """导出所有已注册工具的 Function Schemas。"""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """统一分发并安全执行指定工具。"""
        tool = self.get(name)
        if not tool:
            return ToolResult(f"Error: Tool '{name}' not found.", failed=True)

        try:
            timeout = tool.timeout_seconds
            logger.info(f"Executing tool '{name}' with args {arguments} (timeout: {timeout}s)")
            result = await asyncio.wait_for(tool.execute(**arguments), timeout=timeout)
            if not isinstance(result, ToolResult):
                result = ToolResult(str(result), failed=False)
            return result
        except TimeoutError:
            err_msg = f"Error: Tool '{name}' execution timed out after {tool.timeout_seconds}s."
            logger.error(err_msg)
            return ToolResult(err_msg, failed=True)
        except Exception as e:
            err_msg = f"Error executing tool '{name}': {type(e).__name__}: {e}"
            logger.exception(err_msg)
            return ToolResult(err_msg, failed=True)
