"""Spine 核心调度器：Lane/Worker 会话隔离、抢占打断与并发控制。"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from orangecode.agent.loop import AgentLoop, AgentLoopOutcome
from orangecode.session.manager import SessionManager
from orangecode.spine.events import TurnEnded, TurnEvent, TurnFailed, TurnStarted, Usage
from orangecode.spine.pools import OriginPools
from orangecode.spine.turn import BusyPolicy, TurnHandle, TurnRequest

EventSink = Callable[[TurnEvent], Awaitable[None]]


class Lane:
    """单个会话的专用执行通道，保证同一会话内严格串行，支持任务打断与插队。"""

    def __init__(
        self,
        conversation_id: str,
        pools: OriginPools,
        event_sink: EventSink,
        agent_factory: Callable[[str], AgentLoop],
        session_manager: SessionManager | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.pools = pools
        self.event_sink = event_sink
        self.agent_factory = agent_factory
        self.session_manager = session_manager or SessionManager()

        self._pending: deque[tuple[TurnRequest, asyncio.Future[AgentLoopOutcome]]] = deque()
        self._inject_mailbox: deque[tuple[TurnRequest, asyncio.Future[AgentLoopOutcome]]] = deque()
        self._worker_task: asyncio.Task | None = None
        self._current_run_task: asyncio.Task | None = None

        # 从 SessionManager 恢复历史会话消息（如果存在）
        existing_session = self.session_manager.load(self.conversation_id)
        self._history_messages: list[dict[str, Any]] = (
            existing_session.messages if existing_session else []
        )

    def submit(self, req: TurnRequest) -> asyncio.Future[AgentLoopOutcome]:
        """向当前 Lane 提交 Turn 请求，支持 APPEND、INTERRUPT 与 INJECT 策略。"""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[AgentLoopOutcome] = loop.create_future()

        is_running = self._current_run_task is not None and not self._current_run_task.done()

        if req.busy_policy == BusyPolicy.INTERRUPT and is_running:
            logger.warning(f"Lane [{self.conversation_id}] INTERRUPT: Cancelling current running turn.")
            assert self._current_run_task is not None
            self._current_run_task.cancel()
            self._pending.appendleft((req, fut))
        elif req.busy_policy == BusyPolicy.INJECT and is_running:
            logger.info(f"Lane [{self.conversation_id}] INJECT: Queued into inject mailbox.")
            self._inject_mailbox.append((req, fut))
            return fut
        else:
            self._pending.append((req, fut))

        if self._worker_task is None or self._worker_task.done():
            self._worker_task = loop.create_task(self._run_worker())

        return fut

    def cancel_future(self, fut: asyncio.Future) -> bool:
        """取消指定 Future。"""
        # 1. 尝试从排队中移除
        for item in list(self._pending):
            if item[1] is fut:
                self._pending.remove(item)
                fut.cancel()
                return True
        # 2. 如果正在执行，取消当前 task
        if self._current_run_task and not self._current_run_task.done():
            self._current_run_task.cancel()
            return True
        return False

    async def _run_worker(self) -> None:
        """Lane 的常驻后台 Worker：逐一从队列消费请求并在并发池配额下执行。"""
        while self._pending:
            req, fut = self._pending.popleft()
            if fut.cancelled():
                continue

            sem = self.pools.get_semaphore(req.origin)
            async with sem:
                # 触发 TurnStarted 生命周期事件
                await self.event_sink(
                    TurnStarted(
                        conversation_id=self.conversation_id,
                        turn_id=req.turn_id,
                    )
                )

                agent = self.agent_factory(self.conversation_id)

                # 将当前任务作为独立 Task 执行，便于接收 cancel()
                loop = asyncio.get_running_loop()
                self._current_run_task = loop.create_task(
                    agent.run(
                        prompt=req.prompt,
                        history=self._history_messages,
                    )
                )

                try:
                    outcome: AgentLoopOutcome = await self._current_run_task
                    # 更新当前 Lane 会话历史并持久化 Checkpoint
                    self._history_messages = outcome.messages
                    self.session_manager.save(self.conversation_id, self._history_messages)

                    # 触发 TurnEnded 事件
                    usage = Usage(
                        prompt_tokens=outcome.total_usage.prompt_tokens,
                        completion_tokens=outcome.total_usage.completion_tokens,
                        total_tokens=outcome.total_usage.total_tokens,
                    )
                    await self.event_sink(
                        TurnEnded(
                            conversation_id=self.conversation_id,
                            turn_id=req.turn_id,
                            final_content=outcome.final_content,
                            usage=usage,
                        )
                    )
                    if not fut.done():
                        fut.set_result(outcome)
                except asyncio.CancelledError:
                    err_msg = f"Turn {req.turn_id} was cancelled or interrupted."
                    logger.warning(err_msg)
                    await self.event_sink(
                        TurnFailed(
                            conversation_id=self.conversation_id,
                            turn_id=req.turn_id,
                            error=err_msg,
                        )
                    )
                    if not fut.done():
                        fut.set_exception(asyncio.CancelledError(err_msg))
                except Exception as e:
                    logger.exception(f"Turn {req.turn_id} failed with error: {e}")
                    await self.event_sink(
                        TurnFailed(
                            conversation_id=self.conversation_id,
                            turn_id=req.turn_id,
                            error=str(e),
                        )
                    )
                    if not fut.done():
                        fut.set_exception(e)
                finally:
                    self._current_run_task = None

                # 检查 mailbox 中未被合并的 inject 消息，回退并入 _pending
                while self._inject_mailbox:
                    inj_req, inj_fut = self._inject_mailbox.popleft()
                    self._pending.append((inj_req, inj_fut))


class SpineScheduler:
    """Spine 调度总线：负责管理多会话 Lane、并发隔离与全局生命周期。"""

    def __init__(
        self,
        agent_factory: Callable[[str], AgentLoop],
        pools: OriginPools | None = None,
        event_sink: EventSink | None = None,
        session_manager: SessionManager | None = None,
    ) -> None:
        self.agent_factory = agent_factory
        self.pools = pools or OriginPools()
        self.event_sink = event_sink or self._default_event_sink
        self.session_manager = session_manager or SessionManager()
        self._lanes: dict[str, Lane] = {}
        self._closing = False

    @staticmethod
    async def _default_event_sink(event: TurnEvent) -> None:
        """默认静默或简要记录事件日志。"""
        logger.debug(f"Spine Event: {type(event).__name__}")

    def submit(self, req: TurnRequest) -> TurnHandle:
        """提交请求进入调度系统。"""
        if self._closing:
            raise RuntimeError("Scheduler is shutting down, rejecting new submissions.")

        lane = self._lanes.get(req.conversation_id)
        if not lane:
            lane = Lane(
                conversation_id=req.conversation_id,
                pools=self.pools,
                event_sink=self.event_sink,
                agent_factory=self.agent_factory,
                session_manager=self.session_manager,
            )
            self._lanes[req.conversation_id] = lane

        fut = lane.submit(req)
        return TurnHandle(
            request=req,
            future=fut,
            cancel_fn=lane.cancel_future,
        )

    async def shutdown(self) -> None:
        """优雅关闭调度器。"""
        self._closing = True
        logger.info("SpineScheduler shutting down...")
        # 等待所有 Lane 的 worker 执行完毕
        tasks = [lane._worker_task for lane in self._lanes.values() if lane._worker_task and not lane._worker_task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
