"""TUI RPC 交互代理器：管理确认提示与多选问答的异步请求-应答生命周期。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from loguru import logger

SendFrame = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class _PendingConfirm:
    future: asyncio.Future
    default: bool


class ConfirmBroker:
    """管理向前端/TUI 发出确认提示并等待回答的交互代理。"""

    def __init__(self, send_frame: SendFrame | None = None) -> None:
        self._send_frame = send_frame
        self._pending: dict[str, _PendingConfirm] = {}

    def set_send_frame(self, send_frame: SendFrame) -> None:
        self._send_frame = send_frame

    async def await_confirm(
        self,
        prompt: str,
        *,
        default: bool = False,
        timeout_seconds: float = 35.0,
    ) -> bool:
        """发出 confirm.request 并挂起等待前端用户回答。超时或异常时自动回退为 default。"""
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[request_id] = _PendingConfirm(future=future, default=default)

        try:
            if self._send_frame:
                await self._send_frame({
                    "jsonrpc": "2.0",
                    "method": "confirm.request",
                    "params": {
                        "request_id": request_id,
                        "prompt": prompt,
                        "default": default,
                    },
                })
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning(f"Confirm request '{request_id}' timed out after {timeout_seconds}s; fallback to {default}")
            return default
        except Exception as e:
            logger.exception(f"Error awaiting confirm for '{request_id}': {e}")
            return default
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, answer: bool) -> bool:
        """接收前端提交的确认结果并唤醒等待协程。"""
        pending = self._pending.get(request_id)
        if pending is None or pending.future.done():
            return False
        pending.future.set_result(answer)
        return True

    def cancel_all(self) -> None:
        """安全收敛所有等待中的确认请求至其默认值。"""
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.set_result(pending.default)


@dataclass
class _PendingQuestion:
    future: asyncio.Future
    request_id: str
    default: str


class QuestionBroker:
    """管理向用户或前端发起提问/反问澄清的交互代理。"""

    def __init__(self, send_frame: SendFrame | None = None) -> None:
        self._send_frame = send_frame
        self._pending: dict[str, _PendingQuestion] = {}
        self._by_request: dict[str, str] = {}

    def set_send_frame(self, send_frame: SendFrame) -> None:
        self._send_frame = send_frame

    async def await_question(
        self,
        conversation_id: str,
        *,
        prompt: str,
        choices: list[str] | None = None,
        default: str = "",
        timeout_seconds: float = 600.0,
    ) -> str:
        """发出 clarify.request 并挂起等待前端作答。"""
        # 同一会话如果存在未完成提问，先以默认值收敛旧提问
        existing = self._pending.get(conversation_id)
        if existing is not None:
            logger.warning(f"Overlapping question for session '{conversation_id}', completing stale with default.")
            self._by_request.pop(existing.request_id, None)
            if not existing.future.done():
                existing.future.set_result(existing.default)

        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[conversation_id] = _PendingQuestion(future=future, request_id=request_id, default=default)
        self._by_request[request_id] = conversation_id

        try:
            if self._send_frame:
                await self._send_frame({
                    "jsonrpc": "2.0",
                    "method": "clarify.request",
                    "params": {
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                        "question": prompt,
                        "choices": choices or [],
                    },
                })
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning(f"Question request for session '{conversation_id}' timed out after {timeout_seconds}s.")
            return default
        except Exception as e:
            logger.exception(f"Error awaiting question for '{conversation_id}': {e}")
            return default
        finally:
            current = self._pending.get(conversation_id)
            if current is not None and current.request_id == request_id:
                self._pending.pop(conversation_id, None)
            self._by_request.pop(request_id, None)

    def pending_req(self, conversation_id: str) -> str | None:
        """查询指定会话当前正在等待的 request_id。"""
        pending = self._pending.get(conversation_id)
        return pending.request_id if pending else None

    def reply(self, key: str, answer: str) -> bool:
        """支持通过 conversation_id 或 request_id 回填答案。"""
        cid = key if key in self._pending else self._by_request.get(key)
        if not cid:
            return False
        pending = self._pending.get(cid)
        if pending is None or pending.future.done():
            return False
        pending.future.set_result(answer)
        return True

    def cancel_all(self) -> None:
        """关闭时释放所有挂起的提问。"""
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.set_result(pending.default)
