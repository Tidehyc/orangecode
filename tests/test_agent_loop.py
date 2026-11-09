"""测试 Agent Loop 核心逻辑与工具调用循环。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from orangecode.agent.loop.main import AgentLoop
from orangecode.agent.tools.base import Tool, ToolRegistry, ToolResult
from orangecode.agent.tools.builtin import ReadFileTool, WriteFileTool
from orangecode.providers.base import (
    LLMProvider,
    LLMResponse,
    StreamChunk,
    TokenUsage,
    ToolCallRequest,
)


class MockProvider(LLMProvider):
    """模拟大模型响应的测试 Provider。"""

    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__("mock-model")
        self.responses = responses
        self.call_history: list[list[dict[str, Any]]] = []

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_history.append(messages)
        if not self.responses:
            return LLMResponse(content="Default fallback mock answer")
        return self.responses.pop(0)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta_content="Mock stream chunk")


class AddNumbersTool(Tool):
    """用于测试的计算加法工具。"""

    name = "add_numbers"
    description = "Add two integers together."
    parameters = {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
        },
        "required": ["a", "b"],
    }

    async def execute(self, a: int, b: int, **kwargs: Any) -> ToolResult:
        return ToolResult(str(a + b))


@pytest.mark.asyncio
async def test_builtin_tools(tmp_path):
    # 测试文件写入与读取
    test_file = tmp_path / "test.txt"
    writer = WriteFileTool()
    res_w = await writer.execute(path=str(test_file), content="Hello OrangeCode")
    assert not res_w.failed

    reader = ReadFileTool()
    res_r = await reader.execute(path=str(test_file))
    assert not res_r.failed
    assert res_r == "Hello OrangeCode"

    # 测试读取不存在的文件
    res_not_found = await reader.execute(path=str(tmp_path / "nonexistent.txt"))
    assert res_not_found.failed


@pytest.mark.asyncio
async def test_agent_loop_direct_answer():
    # 测试无需工具调用的直接回答
    mock_provider = MockProvider([
        LLMResponse(
            content="Hello! How can I help you?",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )
    ])
    agent = AgentLoop(provider=mock_provider)
    outcome = await agent.run("Hi")

    assert outcome.success
    assert outcome.iterations == 1
    assert outcome.final_content == "Hello! How can I help you?"
    assert outcome.total_usage.total_tokens == 18


@pytest.mark.asyncio
async def test_agent_loop_with_tool_call():
    # 测试通过工具调用完成回答的多轮思考
    mock_responses = [
        # 第一轮：模型决策调用加法工具
        LLMResponse(
            content="Let me calculate that for you.",
            tool_calls=[
                ToolCallRequest(
                    id="call_add_1",
                    name="add_numbers",
                    arguments={"a": 40, "b": 2},
                )
            ],
            usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        ),
        # 第二轮：模型拿到工具结果 "42"，给出最终答复
        LLMResponse(
            content="The sum of 40 and 2 is 42.",
            tool_calls=[],
            usage=TokenUsage(prompt_tokens=35, completion_tokens=12, total_tokens=47),
        ),
    ]

    registry = ToolRegistry()
    registry.register(AddNumbersTool())

    mock_provider = MockProvider(mock_responses)
    agent = AgentLoop(provider=mock_provider, tool_registry=registry)

    outcome = await agent.run("Calculate 40 + 2")

    assert outcome.success
    assert outcome.iterations == 2
    assert "42" in outcome.final_content
    assert outcome.total_usage.total_tokens == 77

    # 验证消息流中包含了 system, user, assistant(tool_calls), tool(result), assistant(final)
    roles = [m["role"] for m in outcome.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    assert outcome.messages[3]["content"] == "42"


@pytest.mark.asyncio
async def test_agent_loop_max_iterations_limit():
    # 测试达到最大轮次限制自动退出
    infinite_tool_calls = [
        LLMResponse(
            tool_calls=[
                ToolCallRequest(
                    id=f"call_{i}",
                    name="add_numbers",
                    arguments={"a": i, "b": 1},
                )
            ],
            usage=TokenUsage(total_tokens=10),
        )
        for i in range(10)
    ]

    registry = ToolRegistry()
    registry.register(AddNumbersTool())

    mock_provider = MockProvider(infinite_tool_calls)
    agent = AgentLoop(provider=mock_provider, tool_registry=registry)

    outcome = await agent.run("Infinite loop test", max_iterations=3)

    assert not outcome.success
    assert outcome.iterations == 3
    assert outcome.error_message is not None


@pytest.mark.asyncio
async def test_agent_loop_event_sink():
    events = []

    async def sink(evt):
        events.append(evt)

    mock_responses = [
        LLMResponse(
            content="Adding numbers",
            tool_calls=[ToolCallRequest(id="call_1", name="add_numbers", arguments={"a": 1, "b": 2})],
        ),
        LLMResponse(content="Final sum is 3"),
    ]

    registry = ToolRegistry()
    registry.register(AddNumbersTool())
    agent = AgentLoop(
        provider=MockProvider(mock_responses),
        tool_registry=registry,
        event_sink=sink,
    )

    outcome = await agent.run("Add 1 and 2")
    assert outcome.success
    # 验证捕获到了 ToolEvent (START and COMPLETE) 和 TextDelta
    assert len(events) >= 3
    tool_events = [e for e in events if hasattr(e, "tool_name")]
    assert len(tool_events) == 2
    assert tool_events[0].phase == "start"
    assert tool_events[1].phase == "complete"
    assert tool_events[1].result == "3"

    text_deltas = [e for e in events if hasattr(e, "delta")]
    assert len(text_deltas) == 1
    assert text_deltas[0].delta == "Final sum is 3"

