"""TUI RPC 异步服务宿主与默认标准方法集。"""

import json
from typing import Any

from orangecode import __version__
from orangecode.session.manager import SessionManager
from orangecode.spine.scheduler import SpineScheduler
from orangecode.spine.turn import BusyPolicy, Origin, TurnRequest
from orangecode.tui_rpc.dispatcher import PARSE_ERROR, RpcDispatcher


class TuiRpcServer:
    """服务宿主：管理 RPC 协议解析与系统方法绑定。"""

    def __init__(
        self,
        scheduler: SpineScheduler | None = None,
        session_manager: SessionManager | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.session_manager = session_manager or SessionManager()
        self.dispatcher = RpcDispatcher()
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

        self.dispatcher.register("system/ping", ping_handler)
        self.dispatcher.register("session/list", session_list_handler)
        self.dispatcher.register("turn/submit", turn_submit_handler)

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
