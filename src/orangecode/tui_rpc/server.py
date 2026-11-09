"""TUI RPC 异步服务宿主与默认标准方法集。"""

from __future__ import annotations

import json
from typing import Any

from orangecode import __version__
from orangecode.session.manager import SessionManager
from orangecode.spine.scheduler import SpineScheduler
from orangecode.spine.turn import BusyPolicy, Origin, TurnRequest
from orangecode.tui_rpc.brokers import ConfirmBroker, QuestionBroker
from orangecode.tui_rpc.dispatcher import PARSE_ERROR, RpcDispatcher


class TuiRpcServer:
    """服务宿主：管理 RPC 协议解析、系统方法绑定与前端交互代理。"""

    def __init__(
        self,
        scheduler: SpineScheduler | None = None,
        session_manager: SessionManager | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.session_manager = session_manager or SessionManager()
        self.dispatcher = RpcDispatcher()
        self.confirm_broker = ConfirmBroker()
        self.question_broker = QuestionBroker()
        self._register_default_methods()

    def _register_default_methods(self) -> None:
        # system/ping
        async def ping_handler(params: dict[str, Any]) -> dict[str, Any]:
            return {"status": "pong", "version": __version__}

        # session/list
        async def session_list_handler(params: dict[str, Any]) -> dict[str, Any]:
            sessions = self.session_manager.list_sessions()
            return {
                "sessions": [
                    {
                        "conversation_id": s.conversation_id,
                        "created_at": s.created_at,
                        "updated_at": s.updated_at,
                        "message_count": s.message_count,
                    }
                    for s in sessions
                ]
            }

        # turn/submit
        async def turn_submit_handler(params: dict[str, Any]) -> dict[str, Any]:
            if not self.scheduler:
                raise RuntimeError("SpineScheduler not attached to RPC server.")
            prompt = params.get("prompt", "")
            cid = params.get("conversation_id", "default_tui")
            policy_str = params.get("busy_policy", "append")

            policy = BusyPolicy.APPEND
            if policy_str == "interrupt":
                policy = BusyPolicy.INTERRUPT
            elif policy_str == "inject":
                policy = BusyPolicy.INJECT

            handle = self.scheduler.submit(
                TurnRequest(
                    prompt=prompt,
                    conversation_id=cid,
                    origin=Origin.USER,
                    busy_policy=policy,
                )
            )
            return {"turn_id": handle.turn_id, "conversation_id": cid}

        # confirm.respond / confirm/respond
        async def confirm_respond_handler(params: dict[str, Any]) -> dict[str, Any]:
            request_id = params.get("request_id", "")
            answer = bool(params.get("answer", False))
            ok = self.confirm_broker.resolve(request_id, answer)
            return {"accepted": ok, "request_id": request_id}

        # clarify.respond / question/respond
        async def clarify_respond_handler(params: dict[str, Any]) -> dict[str, Any]:
            key = params.get("key") or params.get("request_id") or params.get("conversation_id", "")
            answer = str(params.get("answer", ""))
            ok = self.question_broker.reply(str(key), answer)
            return {"accepted": ok, "key": key}

        self.dispatcher.register("system/ping", ping_handler)
        self.dispatcher.register("session/list", session_list_handler)
        self.dispatcher.register("turn/submit", turn_submit_handler)
        self.dispatcher.register("confirm.respond", confirm_respond_handler)
        self.dispatcher.register("confirm/respond", confirm_respond_handler)
        self.dispatcher.register("clarify.respond", clarify_respond_handler)
        self.dispatcher.register("question/respond", clarify_respond_handler)

    async def handle_json_line(self, line: str) -> str:
        """处理基于换行符分隔 (NDJSON) 的单条 JSON-RPC 请求帧并返回响应帧字符串。"""
        line_clean = line.strip()
        if not line_clean:
            return ""

        try:
            req_frame = json.loads(line_clean)
        except json.JSONDecodeError as err:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": PARSE_ERROR, "message": f"Parse error: {err}"},
            }
            return json.dumps(err_resp, ensure_ascii=False)

        resp_frame = await self.dispatcher.dispatch(req_frame)
        return json.dumps(resp_frame, ensure_ascii=False)

    def close(self) -> None:
        """服务关闭时安全收敛未决交互。"""
        self.confirm_broker.cancel_all()
        self.question_broker.cancel_all()
