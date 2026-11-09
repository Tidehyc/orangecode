import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from orangecode.agent.tools.base import ToolRegistry
from orangecode.agent.tools.mcp import MCPToolWrapper


@dataclass
class DummyTextContent:
    text: str


@dataclass
class DummyCallResult:
    content: list[Any]
    is_error: bool = False


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_success():
    async def mock_call(tool_name: str, args: dict):
        assert tool_name == "query_db"
        assert args == {"sql": "SELECT 1"}
        return DummyCallResult(
            content=[DummyTextContent(text="row 1: 1"), DummyTextContent(text="1 row returned")],
            is_error=False,
        )

    tool = MCPToolWrapper(
        server_name="postgres",
        tool_name="query_db",
        description="Run query",
        parameters={"type": "object", "properties": {"sql": {"type": "string"}}},
        call_fn=mock_call,
    )

    assert tool.name == "mcp_postgres_query_db"
    assert tool.description == "Run query"

    res = await tool.execute(sql="SELECT 1")
    assert not res.failed
    assert "row 1: 1" in res
    assert "1 row returned" in res


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_error_flag():
    async def mock_call(tool_name: str, args: dict):
        return DummyCallResult(
            content=[DummyTextContent(text="syntax error at position 5")],
            is_error=True,
        )

    tool = MCPToolWrapper(
        server_name="postgres",
        tool_name="query_db",
        description="Run query",
        parameters={},
        call_fn=mock_call,
    )

    res = await tool.execute(sql="INVALID SQL")
    assert res.failed
    assert "syntax error" in res


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_timeout():
    async def slow_call(tool_name: str, args: dict):
        await asyncio.sleep(0.5)
        return "Done"

    tool = MCPToolWrapper(
        server_name="slow_server",
        tool_name="slow_op",
        description="Slow operation",
        parameters={},
        call_fn=slow_call,
        timeout_seconds=0.05,
    )

    res = await tool.execute()
    assert res.failed
    assert "timed out after 0.05s" in res


@pytest.mark.asyncio
async def test_mcp_tool_in_registry():
    async def ping_call(name: str, args: dict):
        return "pong"

    tool = MCPToolWrapper(
        server_name="echo",
        tool_name="ping",
        description="Ping server",
        parameters={},
        call_fn=ping_call,
    )

    registry = ToolRegistry()
    registry.register(tool)

    assert registry.get("mcp_echo_ping") is not None
    schemas = registry.list_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "mcp_echo_ping"

    res = await registry.execute("mcp_echo_ping", {})
    assert not res.failed
    assert str(res) == "pong"
