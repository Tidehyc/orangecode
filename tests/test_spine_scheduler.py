"""测试 Spine 调度总线：Lane 串行排队、跨会话并发、任务打断与会话恢复。"""

import asyncio
from typing import Any

import pytest

from orangecode.agent.loop import AgentLoop
from orangecode.agent.tools.base import ToolRegistry
from orangecode.providers.base import LLMProvider, LLMResponse, StreamChunk
from orangecode.session.manager import SessionManager
from orangecode.spine.events import TurnEnded, TurnEvent, TurnStarted
from orangecode.spine.scheduler import SpineScheduler
from orangecode.spine.turn import BusyPolicy, TurnRequest


class DelayedMockProvider(LLMProvider):
    """可自定义延迟与回复的 Mock Provider。"""

    def __init__(self, delay: float = 0.0, reply_prefix: str = "Reply") -> None:
        super().__init__("mock-model")
        self.delay = delay
        self.reply_prefix = reply_prefix
        self.call_count = 0

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        last_msg = messages[-1]["content"]
        return LLMResponse(content=f"{self.reply_prefix}: {last_msg}")

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ):
        yield StreamChunk(delta_content="test")


@pytest.mark.asyncio
async def test_lane_serial_execution(tmp_path):
    # 同一会话内部严格串行执行
    events: list[TurnEvent] = []

    async def record_event(evt: TurnEvent):
        events.append(evt)

    provider = DelayedMockProvider(delay=0.05)
    session_mgr = SessionManager(base_dir=tmp_path)

    def agent_factory(cid: str) -> AgentLoop:
        return AgentLoop(provider=provider, tool_registry=ToolRegistry())

    scheduler = SpineScheduler(
        agent_factory=agent_factory,
        event_sink=record_event,
        session_manager=session_mgr,
    )

    req1 = TurnRequest(prompt="Message 1", conversation_id="conv-1")
    req2 = TurnRequest(prompt="Message 2", conversation_id="conv-1")

    h1 = scheduler.submit(req1)
    h2 = scheduler.submit(req2)

    res1, res2 = await asyncio.gather(h1.wait(), h2.wait())
    assert res1.final_content == "Reply: Message 1"
    assert res2.final_content == "Reply: Message 2"

    # 验证事件顺序：TurnStarted(1) -> TurnEnded(1) -> TurnStarted(2) -> TurnEnded(2)
    started_turns = [e.turn_id for e in events if isinstance(e, TurnStarted)]
    ended_turns = [e.turn_id for e in events if isinstance(e, TurnEnded)]
    assert started_turns == [req1.turn_id, req2.turn_id]
    assert ended_turns == [req1.turn_id, req2.turn_id]

    await scheduler.shutdown()


@pytest.mark.asyncio
async def test_cross_conversation_concurrency(tmp_path):
    # 不同会话可以跨 Lane 并发执行
    provider = DelayedMockProvider(delay=0.1)
    session_mgr = SessionManager(base_dir=tmp_path)

    scheduler = SpineScheduler(
        agent_factory=lambda cid: AgentLoop(provider=provider),
        session_manager=session_mgr,
    )

    start_time = asyncio.get_running_loop().time()
    h1 = scheduler.submit(TurnRequest(prompt="A", conversation_id="conv-A"))
    h2 = scheduler.submit(TurnRequest(prompt="B", conversation_id="conv-B"))

    await asyncio.gather(h1.wait(), h2.wait())
    elapsed = asyncio.get_running_loop().time() - start_time

    # 如果是串行则需要 0.2s+，并发完成应接近 0.1s
    assert elapsed < 0.18

    await scheduler.shutdown()


@pytest.mark.asyncio
async def test_interrupt_busy_policy(tmp_path):
    # 测试打断当前长耗时任务
    provider = DelayedMockProvider(delay=0.5)
    session_mgr = SessionManager(base_dir=tmp_path)

    scheduler = SpineScheduler(
        agent_factory=lambda cid: AgentLoop(provider=provider),
        session_manager=session_mgr,
    )

    # 提交一个耗时 0.5s 的任务
    req_slow = TurnRequest(prompt="Slow task", conversation_id="conv-interrupt")
    h_slow = scheduler.submit(req_slow)

    await asyncio.sleep(0.05)  # 确保 slow task 已经开始运行

    # 提交 INTERRUPT 打断请求
    req_fast = TurnRequest(
        prompt="Immediate urgent task",
        conversation_id="conv-interrupt",
        busy_policy=BusyPolicy.INTERRUPT,
    )
    h_fast = scheduler.submit(req_fast)

    # h_slow 应该被 CancelledError 终止
    with pytest.raises(asyncio.CancelledError):
        await h_slow.wait()

    # h_fast 正常完成
    res_fast = await h_fast.wait()
    assert "Immediate urgent task" in res_fast.final_content

    await scheduler.shutdown()


@pytest.mark.asyncio
async def test_session_persistence_and_restore(tmp_path):
    # 测试会话持久化与上下文自动连贯
    session_mgr = SessionManager(base_dir=tmp_path)
    provider = DelayedMockProvider(delay=0.0)

    scheduler = SpineScheduler(
        agent_factory=lambda cid: AgentLoop(provider=provider),
        session_manager=session_mgr,
    )

    cid = "persist-session-test"
    # 第 1 轮
    h1 = scheduler.submit(TurnRequest(prompt="My name is Alice", conversation_id=cid))
    await h1.wait()

    # 检查磁盘中是否保存了 Checkpoint
    saved = session_mgr.load(cid)
    assert saved is not None
    assert saved.metadata.message_count >= 2

    # 第 2 轮（Lane 自动持有之前的 Alice 记忆）
    h2 = scheduler.submit(TurnRequest(prompt="Who am I?", conversation_id=cid))
    res2 = await h2.wait()

    # 消息链中必须包含之前的 Alice 记录
    all_user_prompts = [m["content"] for m in res2.messages if m["role"] == "user"]
    assert "My name is Alice" in all_user_prompts
    assert "Who am I?" in all_user_prompts

    await scheduler.shutdown()
