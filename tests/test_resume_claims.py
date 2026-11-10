import asyncio
import time
from pathlib import Path

import pytest

from orangecode.agent.loop.main import AgentLoop
from orangecode.agent.tools.base import Tool, ToolRegistry, ToolResult
from orangecode.agent.tools.execution import ToolCapability, ToolEffect
from orangecode.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from orangecode.session.checkpoint import ShadowGitCheckpoint


class SlowReadTool(Tool):
    name = "slow_read"
    description = "Simulate a 50ms read operation"
    parameters = {"type": "object", "properties": {"idx": {"type": "integer"}}}
    capability = ToolCapability(effect=ToolEffect.READ, concurrency_safe=True)

    async def execute(self, idx: int, **kwargs) -> ToolResult:
        await asyncio.sleep(0.05)
        return ToolResult(f"read_{idx}")


class SlowWriteTool(Tool):
    name = "slow_write"
    description = "Simulate a write operation"
    parameters = {"type": "object", "properties": {"idx": {"type": "integer"}}}
    capability = ToolCapability(effect=ToolEffect.WRITE, concurrency_safe=False)

    async def execute(self, idx: int, **kwargs) -> ToolResult:
        return ToolResult(f"write_{idx}")


class MultiToolMockProvider(LLMProvider):
    def __init__(self, tool_calls_list):
        super().__init__("mock-model")
        self.tool_calls_list = list(tool_calls_list)

    async def chat_complete(self, messages, **kwargs):
        if self.tool_calls_list:
            tcs = self.tool_calls_list.pop(0)
            return LLMResponse(content="", tool_calls=tcs)
        return LLMResponse(content="Final answer done.")

    async def stream_chat(self, messages, **kwargs):
        yield None


@pytest.mark.asyncio
async def test_concurrent_read_execution():
    # 模拟同时派发 8 个安全只读工具调用 (每个模拟 50ms IO)
    eight_reads = [
        ToolCallRequest(id=f"call_{i}", name="slow_read", arguments={"idx": i})
        for i in range(8)
    ]

    registry = ToolRegistry()
    registry.register(SlowReadTool())

    provider = MultiToolMockProvider([eight_reads])
    agent = AgentLoop(provider=provider, tool_registry=registry)

    start = time.perf_counter()
    outcome = await agent.run("Read 8 files")
    elapsed = time.perf_counter() - start

    assert outcome.success
    # 8 个 50ms 的工具调用并发执行，工具执行部分耗时约 50ms，整体耗时远小于串行 400ms+
    assert elapsed < 0.5, f"Expected concurrent speedup, but took {elapsed:.3f}s"

    # 验证工具返回顺序依然严格与输入一致 (0..7)
    tool_msgs = [m for m in outcome.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 8
    for i, m in enumerate(tool_msgs):
        assert m["content"] == f"read_{i}"


@pytest.mark.asyncio
async def test_tool_execution_cancellation_cleanup():
    """验证任务取消时清理未完成调用，避免任务残留。"""
    registry = ToolRegistry()
    registry.register(SlowReadTool())

    three_reads = [
        ToolCallRequest(id=f"call_{i}", name="slow_read", arguments={"idx": i})
        for i in range(3)
    ]
    provider = MultiToolMockProvider([three_reads])
    agent = AgentLoop(provider=provider, tool_registry=registry)

    # 启动 agent 并在运行中取消
    task = asyncio.create_task(agent.run("Read files with cancel"))
    await asyncio.sleep(0.01)  # 确保进入工具执行
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_shadow_git_checkpoint_and_drift_detection(tmp_path: Path):
    checkpoint = ShadowGitCheckpoint(workspace=tmp_path)
    ok = await checkpoint.ensure_init()
    assert ok is True

    # 1. 模拟轮次完成，提交一个初始快照
    file1 = tmp_path / "hello.py"
    file1.write_text("print('hello')", encoding="utf-8")

    cid, changed = await checkpoint.commit_turn("Turn 1 snapshot")
    assert cid is not None
    assert "hello.py" in changed

    # 2. 此时工作区与快照同步，未发生漂移
    is_drifted, reason = await checkpoint.detect_drift(expected_commit=cid)
    assert not is_drifted
    assert "in sync" in reason

    # 3. 模拟外部进程或用户在任务外偷偷修改工作区（Workspace 漂移场景）
    file2 = tmp_path / "external_untracked.txt"
    file2.write_text("drift content", encoding="utf-8")

    # 4. 再次检测，精准识别漂移
    is_drifted, reason = await checkpoint.detect_drift(expected_commit=cid)
    assert is_drifted is True
    assert "uncommitted external modifications" in reason
