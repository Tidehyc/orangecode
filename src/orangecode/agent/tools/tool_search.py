"""动态工具搜索与按需分发：针对多工具场景的 Token 节约与动态装配。"""

import json
from typing import Any

from orangecode.agent.tools.base import Tool, ToolResult
from orangecode.agent.tools.execution import ToolCapability, ToolEffect
from orangecode.agent.tools.tool_index import ToolIndex


class ToolSearchTool(Tool):
    """供智能体按需检索环境中可用工具的元搜索工具。"""

    name = "tool_search"
    description = (
        "Search the active tool catalog by keywords or capability description. "
        "Returns tool names, descriptions, and parameter JSON schemas."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keywords or intent describing the desired tool (e.g. 'web browser', 'regex search').",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of tools to return. Defaults to 5.",
            },
        },
        "required": ["query"],
    }
    capability = ToolCapability(effect=ToolEffect.READ, concurrency_safe=True)

    def __init__(self, index: ToolIndex) -> None:
        self.index = index

    async def execute(self, query: str, limit: int = 5, **kwargs: Any) -> ToolResult:
        tools = self.index.search(query, limit=limit)
        if not tools:
            return ToolResult(f"No tools found matching query '{query}'.", failed=False)

        output_parts: list[str] = [f"Found {len(tools)} tool(s) matching '{query}':\n"]
        for t in tools:
            output_parts.append(
                f"### Tool: `{t.name}`\n"
                f"- Description: {t.description}\n"
                f"- Parameters:\n```json\n{json.dumps(t.parameters, indent=2, ensure_ascii=False)}\n```\n"
            )

        return ToolResult("\n".join(output_parts), failed=False)
