"""测试完整的 TUI RPC TCP 服务端、OpenRPC 生命周期与端到端事件流联调。"""

from __future__ import annotations

import asyncio
import json

import pytest

from orangecode.agent.loop import AgentLoop
from orangecode.agent.tools import AskUserTool, ToolRegistry
from orangecode.config import settings
from orangecode.providers.base import LLMProvider, LLMResponse, TokenUsage, ToolCallRequest
from orangecode.session.manager import SessionManager
from orangecode.spine.scheduler import SpineScheduler
from orangecode.tui_rpc.config_store import TuiConfigStore
from orangecode.tui_rpc.server import ERR_MODEL_NOT_AVAILABLE, ERR_SESSION_NOT_FOUND, TuiRpcServer


class _ClarifyMockProvider(LLMProvider):
    """第 1 次调用 ask_user 工具，第 2 次读取回答并输出最终文本。"""

    def __init__(self) -> None:
        super().__init__("deepseek/deepseek-chat")
        self.calls = 0

    async def chat_complete(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="tc_ask_1",
                        name="ask_user",
                        arguments={"question": "Use orange theme?", "options": ["yes", "no"]},
                    )
                ],
                usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                finish_reason="tool_calls",
            )
        tool_reply = next((m.get("content") for m in reversed(messages) if m.get("role") == "tool"), "")
        return LLMResponse(
            content=f"Confirmed choice: {tool_reply}",
            tool_calls=[],
            usage=TokenUsage(prompt_tokens=35, completion_tokens=15, total_tokens=50),
            finish_reason="stop",
        )

    async def stream_chat(self, messages, tools=None, temperature=0.7, max_tokens=None, **kwargs):
        if False:
            yield None


class _TcpRpcTestClient:
    """轻量 NDJSON TCP RPC 客户端（模拟 Node RpcClient 握手与事件队列）。"""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.responses: dict[int | str, dict] = {}
        self.waiters: dict[int | str, asyncio.Future] = {}
        self.notifications: asyncio.Queue[dict] = asyncio.Queue()
        self._next_id = 1
        self._pump_task = asyncio.create_task(self._pump())

    @classmethod
    async def connect(cls, host: str, port: int, token: str | None = None) -> _TcpRpcTestClient:
        reader, writer = await asyncio.open_connection(host, port)
        if token is not None:
            writer.write((token + "\n").encode("utf-8"))
            await writer.drain()
        return cls(reader, writer)

    async def _pump(self) -> None:
        while True:
            raw = await self.reader.readline()
            if not raw:
                break
            frame = json.loads(raw.decode("utf-8"))
            if "id" in frame and frame["id"] is not None:
                fut = self.waiters.pop(frame["id"], None)
                if fut and not fut.done():
                    fut.set_result(frame)
            else:
                await self.notifications.put(frame)

    async def call(self, method: str, params: dict | None = None) -> dict:
        req_id = self._next_id
        self._next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.waiters[req_id] = fut
        frame = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        self.writer.write((json.dumps(frame) + "\n").encode("utf-8"))
        await self.writer.drain()
        resp = await asyncio.wait_for(fut, timeout=3.0)
        return resp

    async def next_notification(self, timeout: float = 3.0) -> dict:
        return await asyncio.wait_for(self.notifications.get(), timeout=timeout)

    async def close(self) -> None:
        self._pump_task.cancel()
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_tcp_auth_rejection(tmp_path):
    mgr = SessionManager(base_dir=tmp_path)
    server = TuiRpcServer(session_manager=mgr, auth_token="secret-tok-123")
    host, port = await server.start_tcp()
    try:
        bad_client = await _TcpRpcTestClient.connect(host, port, token="wrong-tok")
        raw = await bad_client.reader.readline()
        # 连接被立即关闭，读不到任何响应
        assert raw == b""
        await bad_client.close()
    finally:
        await server.aclose()


@pytest.mark.asyncio
async def test_full_openrpc_session_model_and_turn_stream(tmp_path):
    mgr = SessionManager(base_dir=tmp_path)
    cfg = TuiConfigStore(state_dir=tmp_path)
    provider = _ClarifyMockProvider()

    server: TuiRpcServer

    def agent_factory(cid: str) -> AgentLoop:
        reg = ToolRegistry()
        reg.register(
            AskUserTool(
                input_handler=lambda q, opts: server.question_broker.await_question(
                    cid,
                    prompt=q,
                    choices=opts,
                )
            )
        )
        return AgentLoop(
            provider=provider,
            tool_registry=reg,
            event_sink=server._make_agent_sink(cid),
        )

    scheduler = SpineScheduler(
        agent_factory=agent_factory,
        session_manager=mgr,
    )
    server = TuiRpcServer(
        scheduler=scheduler,
        session_manager=mgr,
        config_store=cfg,
        auth_token="tok-xyz",
        cwd=tmp_path,
    )
    # 将 scheduler 事件总线绑定至 server._on_spine_event
    scheduler.event_sink = server._on_spine_event

    host, port = await server.start_tcp()
    client = await _TcpRpcTestClient.connect(host, port, token="tok-xyz")

    try:
        # 1. System + Setup + Terminal
        hello = (await client.call("system.hello", {"client_version": "0.0.2"}))["result"]
        assert "chat" in hello["server_capabilities"]
        assert hello["session"]["default_channel"] == "tui"

        ping = (await client.call("system.ping"))["result"]
        assert ping["pong"] is True

        ver = (await client.call("system.version"))["result"]
        assert "orangecode_version" in ver

        setup = (await client.call("setup.status"))["result"]
        assert setup["provider_configured"] is True

        assert (await client.call("terminal.resize", {"cols": 100, "rows": 30}))["result"]["ok"] is True

        # 2. Model & Config
        opts = (await client.call("model.options"))["result"]
        assert opts["model"] == "deepseek/deepseek-chat"
        saved = (await client.call("model.save_key", {"slug": "deepseek", "api_key": "sk-test-1"}))["result"]
        assert saved["provider"]["authenticated"] is True

        added = (await client.call("model.add_model", {"slug": "deepseek", "model": "deepseek/custom-v3"}))["result"]
        assert "deepseek/custom-v3" in added["provider"]["models"]
        removed = (await client.call("model.remove_model", {"slug": "deepseek", "model": "deepseek/custom-v3"}))["result"]
        assert "deepseek/custom-v3" not in removed["provider"]["models"]

        cfg_res = (await client.call("config.set", {"key": "model", "value": "gpt-4o", "provider": "openai"}))["result"]
        assert cfg_res["applied"] is True and cfg_res["value"] == "gpt-4o"
        assert (await client.call("config.get", {"keys": ["model"]}))["result"]["config"]["model"] == "gpt-4o"

        assert (await client.call("model.disconnect", {"slug": "deepseek"}))["result"]["disconnected"] is True

        # 3. Session Create + Turn Subscribe + Streaming Turn with Clarify Roundtrip
        created = (await client.call("session.create", {"cols": 100}))["result"]
        sid = created["session_id"]
        assert sid.startswith("tui:")

        sub = (await client.call("turn.subscribe", {"session_key": sid}))["result"]
        sub_id = sub["subscription_id"]

        send_res = (
            await client.call(
                "turn.send",
                {"session_key": sid, "content": "Set theme", "submission_id": "sub_001"},
            )
        )["result"]
        assert send_res["accepted"] is True

        events: list[str] = []
        clarify_req_id = ""
        final_text = ""

        # 循环接收通知并在 clarify.request 时作答
        for _ in range(12):
            notif = await client.next_notification()
            if notif["method"] == "clarify.request":
                clarify_req_id = notif["params"]["request_id"]
                assert notif["params"]["choices"] == ["yes", "no"]
                ans = (await client.call("clarify.respond", {"request_id": clarify_req_id, "answer": "yes"}))["result"]
                assert ans["ok"] is True
                continue
            if notif["method"] == "event":
                assert notif["params"]["subscription_id"] == sub_id
                ev = notif["params"]["event"]
                events.append(ev["type"])
                if ev["type"] == "token.delta":
                    final_text += ev["payload"]["text"]
                if ev["type"] == "message.complete":
                    assert ev["payload"]["usage"]["total_tokens"] == 80
                    break

        assert clarify_req_id != ""
        assert events[0] == "message.start"
        assert "tool.start" in events and "tool.complete" in events
        assert "token.delta" in events and events[-1] == "message.complete"
        assert final_text == "Confirmed choice: yes"

        # 4. Title / List / Resume / Branch / Export / Undo / Clear / Delete
        titled = (await client.call("session.title", {"session_id": sid, "title": "Orange TUI Test"}))["result"]
        assert titled["pending"] is False

        listed = (await client.call("session.list"))["result"]["sessions"]
        assert any(row["id"] == sid and row["title"] == "Orange TUI Test" and isinstance(row["started_at"], float) for row in listed)

        recent = (await client.call("session.most_recent"))["result"]
        assert recent["session_id"] == sid

        resumed = (await client.call("session.resume", {"session_id": sid}))["result"]
        assert any(m.get("role") == "assistant" and "Confirmed choice: yes" in m.get("text", "") for m in resumed["messages"])

        branched = (await client.call("session.branch", {"session_id": sid, "name": "fork-1"}))["result"]
        assert branched["session_id"] == "tui:fork-1"

        exported = (await client.call("session.export", {"session_id": sid}))["result"]
        assert exported["exported"] is True and exported["path"].endswith(".md")

        undone = (await client.call("session.undo", {"session_id": sid, "n": 1}))["result"]
        assert undone["removed"] > 0

        cleared = (await client.call("session.clear", {"session_id": sid}))["result"]
        assert cleared["cleared"] is True

        deleted = (await client.call("session.delete", {"session_id": "tui:fork-1"}))["result"]
        assert deleted["deleted"] == "tui:fork-1"

        missing = await client.call("session.resume", {"session_id": "tui:nope"})
        assert missing["error"]["code"] == ERR_SESSION_NOT_FOUND

        assert (await client.call("turn.unsubscribe", {"subscription_id": sub_id}))["result"]["unsubscribed"] is True
        assert (await client.call("session.close", {"session_id": sid}))["result"]["ok"] is True
    finally:
        await client.close()
        await server.aclose()


@pytest.mark.asyncio
async def test_turn_send_without_credentials_emits_clean_error(tmp_path, monkeypatch):
    for var in ("ORANGECODE_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(settings, "api_key", None)

    mgr = SessionManager(base_dir=tmp_path)
    cfg = TuiConfigStore(state_dir=tmp_path)
    server = TuiRpcServer(session_manager=mgr, config_store=cfg, enable_agent_runtime=True, auth_token="tok-nokey")
    host, port = await server.start_tcp()
    client = await _TcpRpcTestClient.connect(host, port, token="tok-nokey")
    try:
        sid = (await client.call("session.create"))["result"]["session_id"]
        await client.call("turn.subscribe", {"session_key": sid})
        ack = (await client.call("turn.send", {"session_key": sid, "content": "hello", "submission_id": "s_nokey"}))["result"]
        assert ack["accepted"] is True

        ev1 = (await client.next_notification())["params"]["event"]
        ev2 = (await client.next_notification())["params"]["event"]
        assert ev1["type"] == "message.start"
        assert ev2["type"] == "error"
        assert ev2["payload"]["code"] == ERR_MODEL_NOT_AVAILABLE
    finally:
        await client.close()
        await server.aclose()
