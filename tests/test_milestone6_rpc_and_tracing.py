"""测试 Milestone 6：JSON-RPC 2.0 分发器、TuiRpcServer 协议栈与 OpenTelemetry Span 链路追踪。"""

import json

import pytest

from orangecode.session.manager import SessionManager
from orangecode.tracing.spans import Tracer
from orangecode.tui_rpc.dispatcher import (
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    RpcDispatcher,
)
from orangecode.tui_rpc.server import TuiRpcServer


@pytest.mark.asyncio
async def test_rpc_dispatcher_routing():
    dispatcher = RpcDispatcher()

    async def mock_echo(params):
        return {"echo": params.get("msg")}

    dispatcher.register("test/echo", mock_echo)

    # 1. 成功请求
    req_valid = {"jsonrpc": "2.0", "id": 1, "method": "test/echo", "params": {"msg": "hello"}}
    resp_valid = await dispatcher.dispatch(req_valid)
    assert resp_valid["result"]["echo"] == "hello"
    assert resp_valid["id"] == 1

    # 2. 方法不存在
    req_missing = {"jsonrpc": "2.0", "id": 2, "method": "non/existent"}
    resp_missing = await dispatcher.dispatch(req_missing)
    assert resp_missing["error"]["code"] == METHOD_NOT_FOUND

    # 3. 非法版本
    req_bad_ver = {"jsonrpc": "1.0", "id": 3, "method": "test/echo"}
    resp_bad_ver = await dispatcher.dispatch(req_bad_ver)
    assert resp_bad_ver["error"]["code"] == INVALID_REQUEST


@pytest.mark.asyncio
async def test_tui_rpc_server_methods(tmp_path):
    session_mgr = SessionManager(base_dir=tmp_path)
    session_mgr.save("session-alpha", [{"role": "user", "content": "hi"}])

    server = TuiRpcServer(session_manager=session_mgr)

    # 1. 测试换行符分隔的 ping 帧
    ping_req = json.dumps({"jsonrpc": "2.0", "id": "p1", "method": "system/ping", "params": {}})
    ping_resp_str = await server.handle_json_line(ping_req)
    ping_resp = json.loads(ping_resp_str)
    assert ping_resp["result"]["status"] == "pong"

    # 2. 测试会话列表查询
    list_req = json.dumps({"jsonrpc": "2.0", "id": "p2", "method": "session/list", "params": {}})
    list_resp_str = await server.handle_json_line(list_req)
    list_resp = json.loads(list_resp_str)
    assert len(list_resp["result"]["sessions"]) >= 1
    assert list_resp["result"]["sessions"][0]["conversation_id"] == "session-alpha"

    # 3. 测试残缺 JSON 解析错误
    bad_req_str = "{bad json string"
    bad_resp_str = await server.handle_json_line(bad_req_str)
    bad_resp = json.loads(bad_resp_str)
    assert bad_resp["error"]["code"] == PARSE_ERROR


def test_tracer_spans():
    tracer = Tracer(service_name="orangecode-test")

    # 1. 成功 Span
    with tracer.start_span("test_operation", attributes={"gen_ai.system": "deepseek"}) as span:
        assert span.name == "test_operation"
        assert span.attributes["gen_ai.system"] == "deepseek"

    assert len(tracer.completed_spans) == 1
    completed = tracer.completed_spans[0]
    assert completed.status == "ok"
    assert completed.duration_ms >= 0.0

    # 2. 异常 Span 自动记录
    with pytest.raises(ValueError):
        with tracer.start_span("failing_operation"):
            raise ValueError("Something went wrong")

    assert len(tracer.completed_spans) == 2
    err_span = tracer.completed_spans[1]
    assert err_span.status == "error"
    assert err_span.attributes["error.type"] == "ValueError"
    assert "Something went wrong" in err_span.attributes["error.message"]
