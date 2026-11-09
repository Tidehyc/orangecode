"""轻量级异步 JSON-RPC 2.0 分发器：驱动 Node.js 原生终端 UI。"""

from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

RpcHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class RpcDispatcher:
    """JSON-RPC 2.0 请求路由与错误隔离中枢。"""

    def __init__(self) -> None:
        self._handlers: dict[str, RpcHandler] = {}

    def register(self, method: str, handler: RpcHandler) -> None:
        """注册 RPC 异步处理函数。"""
        self._handlers[method] = handler
        logger.debug(f"Registered RPC method: {method}")

    async def dispatch(self, request_frame: dict[str, Any]) -> dict[str, Any]:
        """分派单条 JSON-RPC 请求并生成标准响应帧。"""
        req_id = request_frame.get("id")

        if request_frame.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": INVALID_REQUEST, "message": "Invalid JSON-RPC version, expected '2.0'."},
            }

        method = request_frame.get("method")
        if not isinstance(method, str):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": INVALID_REQUEST, "message": "Missing or non-string 'method' in request."},
            }

        handler = self._handlers.get(method)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": METHOD_NOT_FOUND, "message": f"Method '{method}' not found."},
            }

        params = request_frame.get("params") or {}
        if not isinstance(params, dict):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": INVALID_PARAMS, "message": "Parameters must be a JSON object/dict."},
            }

        try:
            result = await handler(params)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }
        except Exception as err:
            logger.exception(f"RPC method '{method}' failed: {err}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": INTERNAL_ERROR, "message": str(err)},
            }
