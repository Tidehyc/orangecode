"""Model Context Protocol (MCP) 客户端工具包装器与连接管理。"""

import asyncio
from typing import Any

from loguru import logger

from orangecode.agent.tools.base import Tool, ToolResult
from orangecode.agent.tools.execution import ToolCapability, ToolEffect


class MCPToolWrapper(Tool):
    """把外部 MCP Server 提供的 Tool 适配为 OrangeCode 原生 Tool 实例。"""

    capability = ToolCapability(effect=ToolEffect.EXTERNAL, concurrency_safe=False)

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        parameters: dict[str, Any],
        call_fn: Any,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.server_name = server_name
        self.original_name = tool_name
        self.name = f"mcp_{server_name}_{tool_name}"
        self.description = description or f"MCP tool '{tool_name}' from server '{server_name}'"
        self.parameters = parameters or {"type": "object", "properties": {}}
        self.timeout_seconds = timeout_seconds
        self._call_fn = call_fn

    async def execute(self, **kwargs: Any) -> ToolResult:
        """分发调用至 MCP 远端 Server 并捕获响应。"""
        try:
            logger.debug(f"Calling MCP tool '{self.original_name}' on server '{self.server_name}' with {kwargs}")
            raw_result = await asyncio.wait_for(
                self._call_fn(self.original_name, kwargs),
                timeout=self.timeout_seconds,
            )

            # 兼容 MCP 官方 SDK 返回的 CallToolResult 结构
            is_error = getattr(raw_result, "isError", getattr(raw_result, "is_error", False))
            content_items = getattr(raw_result, "content", None)

            if isinstance(content_items, list):
                text_parts = []
                for item in content_items:
                    text_parts.append(getattr(item, "text", str(item)))
                output_str = "\n".join(text_parts)
            elif isinstance(raw_result, str):
                output_str = raw_result
            else:
                output_str = str(raw_result)

            return ToolResult(output_str, failed=bool(is_error))
        except asyncio.TimeoutError:
            return ToolResult(
                f"Error: MCP tool '{self.name}' timed out after {self.timeout_seconds}s.",
                failed=True,
            )
        except Exception as e:
            return ToolResult(f"Error calling MCP tool '{self.name}': {e}", failed=True)
