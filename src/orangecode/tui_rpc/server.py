"""TUI RPC 异步服务宿主与标准 OpenRPC 方法集。"""

from __future__ import annotations

import asyncio
import hmac
import json
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from loguru import logger

from orangecode import __version__
from orangecode.session.manager import SessionManager, SessionRecord
from orangecode.spine.events import (
    Notice,
    TextDelta,
    ToolEvent,
    ToolPhase,
    TurnEnded,
    TurnEvent,
    TurnFailed,
    TurnStarted,
)
from orangecode.spine.scheduler import SpineScheduler
from orangecode.spine.turn import BusyPolicy, Origin, TurnHandle, TurnRequest
from orangecode.tui_rpc.brokers import ConfirmBroker, QuestionBroker
from orangecode.tui_rpc.config_store import TuiConfigStore, infer_provider_slug
from orangecode.tui_rpc.dispatcher import PARSE_ERROR, RpcDispatcher, RpcMethodError

if TYPE_CHECKING:
    from orangecode.agent.loop import AgentLoop
    from orangecode.agent.tools import ToolRegistry

MAX_FRAME_BYTES = 1024 * 1024  # 1 MiB
ERR_SESSION_NOT_FOUND = -32001
ERR_TURN_IN_PROGRESS = -32003
ERR_MODEL_NOT_AVAILABLE = -32008
ERR_CONFIG_READONLY = -32010
ERR_CONFIG_VALIDATION = -32011
ERR_NOT_SUPPORTED = -32012

DEFAULT_SYSTEM_PROMPT = "You are OrangeCode, a helpful and precise agent assistant."
DEFAULT_CONTEXT_MAX = 128_000


def _iso_to_unix_ts(raw: str) -> float:
    if not raw:
        return time.time()
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return time.time()


_BUILTIN_TOOL_GROUPS: dict[str, list[str]] = {
    "filesystem": ["read_file", "write_file", "edit_file", "list_dir"],
    "search": ["find", "grep"],
    "execution": ["execute_bash"],
    "interaction": ["ask_user"],
    "web": ["web_fetch", "web_search"],
}


def _discover_skills(state_dir: Path) -> dict[str, list[str]]:
    skills_dir = state_dir / "skills"
    if not skills_dir.exists():
        return {}
    from orangecode.memory_engine.skill_local import SkillWatcher

    watcher = SkillWatcher(skills_dir)
    if not watcher.skills:
        return {}
    grouped: dict[str, list[str]] = {}
    for name, skill in watcher.skills.items():
        cat = skill.path.parent.name if skill.path and skill.path.parent != skills_dir.resolve() else "local"
        grouped.setdefault(cat, []).append(name)
    return grouped


def _session_preview(messages: list[dict[str, Any]]) -> str:
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            text = " ".join(msg["content"].split())
            if text:
                return text[:80]
    return ""


def _to_transcript_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将内部 OpenAI 对话消息格式转换为前端 SessionMessage 列表。"""
    out: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content")
        if role == "system" and idx == 0:
            continue
        if role == "tool":
            name = str(msg.get("name") or "tool")
            ctx = str(content or "")
            out.append({"role": "tool", "name": name, "context": " ".join(ctx.split())[:120]})
            continue
        if role in ("user", "assistant", "system") and isinstance(content, str) and content.strip():
            out.append({"role": role, "text": content})
    return out


class TuiRpcServer:
    """服务宿主：管理 JSON-RPC 2.0 协议分发、事件流订阅、会话管理与 TCP/Socket 服务循环。"""

    def __init__(
        self,
        scheduler: SpineScheduler | None = None,
        session_manager: SessionManager | None = None,
        *,
        config_store: TuiConfigStore | None = None,
        auth_token: str | None = None,
        cwd: Path | str | None = None,
        enable_agent_runtime: bool = False,
        default_system_prompt: str | None = None,
    ) -> None:
        self.session_manager = session_manager or SessionManager()
        self.config_store = config_store or TuiConfigStore(state_dir=self.session_manager.base_dir.parent)
        self.auth_token = auth_token
        self.cwd = Path(cwd).resolve() if cwd else Path.cwd()
        self.system_prompt = default_system_prompt or DEFAULT_SYSTEM_PROMPT
        self.dispatcher = RpcDispatcher()
        self.confirm_broker = ConfirmBroker()
        self.question_broker = QuestionBroker()
        self._owns_scheduler = False

        if scheduler is not None:
            self.scheduler: SpineScheduler | None = scheduler
        elif enable_agent_runtime:
            self.scheduler = SpineScheduler(
                agent_factory=self._build_agent_for_session,
                event_sink=self._on_spine_event,
                session_manager=self.session_manager,
            )
            self._owns_scheduler = True
        else:
            self.scheduler = None

        # 传输层与异步订阅状态
        self._server: asyncio.AbstractServer | None = None
        self._active_writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()
        self._conn_tasks: set[asyncio.Task[Any]] = set()
        self._closed = False

        # 会话/轮次/事件跟踪
        self._sessions: dict[str, dict[str, Any]] = {}
        self._subscriptions: dict[str, str] = {}  # subscription_id -> session_key
        self._turn_submissions: dict[tuple[str, str], str] = {}  # (cid, turn_id) -> submission_id
        self._latest_turn_by_cid: dict[str, str] = {}
        self._active_handles: dict[str, TurnHandle] = {}
        self._inflight_tools: dict[str, deque[tuple[str, str]]] = {}
        self._emitted_text_turns: set[str] = set()
        self._session_usage: dict[str, dict[str, Any]] = {}
        self._terminal_size: tuple[int, int] = (100, 24)

        self.confirm_broker.set_send_frame(self._send_frame)
        self.question_broker.set_send_frame(self._send_frame)
        self._register_default_methods()

    # ── 工具与 Agent 构造 ─────────────────────────────────────────────

    def _build_tool_registry(self, conversation_id: str) -> ToolRegistry:
        from orangecode.agent.tools import (
            AskUserTool,
            BashTool,
            EditFileTool,
            FindTool,
            GrepTool,
            ListDirTool,
            ReadFileTool,
            ToolRegistry,
            WebFetchTool,
            WebSearchTool,
            WriteFileTool,
        )

        registry = ToolRegistry()
        for tool in (
            ReadFileTool(),
            WriteFileTool(),
            EditFileTool(),
            ListDirTool(),
            FindTool(),
            GrepTool(),
            BashTool(),
            WebFetchTool(),
            WebSearchTool(),
            AskUserTool(
                input_handler=lambda q, opts: self.question_broker.await_question(
                    conversation_id,
                    prompt=q,
                    choices=opts,
                )
            ),
        ):
            registry.register(tool)
        return registry

    def _build_agent_for_session(self, conversation_id: str) -> AgentLoop:
        from orangecode.agent.loop import AgentLoop
        from orangecode.providers import LiteLLMProvider

        model = self.config_store.model
        provider_slug = self.config_store.provider or infer_provider_slug(model)
        api_key, api_base = self.config_store.resolve_credentials(model, provider_slug)
        provider = LiteLLMProvider(
            model_name=model,
            api_key=api_key,
            api_base=api_base,
        )
        registry = self._build_tool_registry(conversation_id)
        return AgentLoop(
            provider=provider,
            tool_registry=registry,
            default_system_prompt=self.system_prompt,
            event_sink=self._make_agent_sink(conversation_id),
        )

    def _make_agent_sink(self, conversation_id: str) -> Callable[[TurnEvent], Any]:
        async def _sink(event: TurnEvent) -> None:
            await self._on_agent_event(conversation_id, event)

        return _sink

    # ── 会话信息与用量辅助 ────────────────────────────────────────────

    def _ensure_session_entry(self, sid: str) -> dict[str, Any]:
        if sid not in self._sessions:
            record = self.session_manager.load(sid)
            extra = dict(record.metadata.extra) if record else {}
            created_at = _iso_to_unix_ts(record.metadata.created_at) if record else time.time()
            self._sessions[sid] = {"title": str(extra.get("title") or ""), "created_at": created_at}
        return self._sessions[sid]

    def _usage_for(self, sid: str) -> dict[str, Any]:
        return dict(
            self._session_usage.get(
                sid,
                {
                    "calls": 0,
                    "input": 0,
                    "output": 0,
                    "total": 0,
                    "context_used": 0,
                    "context_max": DEFAULT_CONTEXT_MAX,
                    "context_percent": 0,
                    "cost_usd": 0.0,
                },
            )
        )

    def _build_session_info(self, sid: str | None = None) -> dict[str, Any]:
        model = self.config_store.model
        provider_slug = self.config_store.provider or infer_provider_slug(model)
        info: dict[str, Any] = {
            "model": model,
            "provider": provider_slug,
            "version": __version__,
            "cwd": str(self.cwd),
            "system_prompt": self.system_prompt,
            "tools": {k: list(v) for k, v in _BUILTIN_TOOL_GROUPS.items()},
            "skills": _discover_skills(self.session_manager.base_dir.parent),
            "mcp_servers": [],
            "context_window": DEFAULT_CONTEXT_MAX,
            "usage": self._usage_for(sid or ""),
        }
        if self.config_store.reasoning_effort:
            info["reasoning_effort"] = self.config_store.reasoning_effort
        if not self.config_store.has_any_credentials():
            info["credential_warning"] = "No API key set — run /model to configure."
        return info

    def _load_or_error(self, sid: str) -> SessionRecord:
        record = self.session_manager.load(sid)
        if record is not None:
            return record
        entry = self._sessions.get(sid)
        if entry is not None:
            return self.session_manager.save(sid, [], extra={"title": entry.get("title", "")})
        raise RpcMethodError(ERR_SESSION_NOT_FOUND, f"Session not found: {sid}")

    def _sync_lane_history(self, sid: str, messages: list[dict[str, Any]]) -> None:
        if self.scheduler and sid in self.scheduler._lanes:
            self.scheduler._lanes[sid]._history_messages = list(messages)

    # ── JSON-RPC 帧发送与 Spine 事件转发 ───────────────────────────────

    async def _send_frame(self, frame: dict[str, Any]) -> None:
        writer = self._active_writer
        if writer is None or writer.is_closing():
            return
        line = (json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8")
        async with self._write_lock:
            if self._active_writer is not writer or writer.is_closing():
                return
            writer.write(line)
            await writer.drain()

    async def _emit_to_session(self, conversation_id: str, event_payload: dict[str, Any]) -> None:
        targets = [sub_id for sub_id, cid in self._subscriptions.items() if cid == conversation_id]
        for sub_id in targets:
            await self._send_frame(
                {
                    "jsonrpc": "2.0",
                    "method": "event",
                    "params": {
                        "subscription_id": sub_id,
                        "event": event_payload,
                    },
                }
            )

    async def _on_agent_event(self, cid: str, event: TurnEvent) -> None:
        if isinstance(event, TextDelta):
            turn_id = self._latest_turn_by_cid.get(cid)
            if turn_id:
                self._emitted_text_turns.add(turn_id)
            if event.delta:
                await self._emit_to_session(cid, {"type": "token.delta", "payload": {"text": event.delta}})
            return

        if isinstance(event, ToolEvent):
            queue = self._inflight_tools.setdefault(cid, deque())
            if event.phase == ToolPhase.START:
                call_id = f"tc_{uuid4().hex[:10]}"
                queue.append((event.tool_name, call_id))
                await self._emit_to_session(
                    cid,
                    {
                        "type": "tool.start",
                        "payload": {
                            "tool_call_id": call_id,
                            "name": event.tool_name,
                            "arguments": event.arguments or {},
                        },
                    },
                )
            else:
                call_id = ""
                for idx in range(len(queue) - 1, -1, -1):
                    if queue[idx][0] == event.tool_name:
                        _, call_id = queue[idx]
                        del queue[idx]
                        break
                if not call_id:
                    call_id = f"tc_{uuid4().hex[:10]}"
                raw = event.result or ""
                truncated = len(raw) > 400
                preview = raw[:400]
                await self._emit_to_session(
                    cid,
                    {
                        "type": "tool.complete",
                        "payload": {
                            "tool_call_id": call_id,
                            "result_preview": preview,
                            "failed": event.failed,
                            "truncated": truncated,
                        },
                    },
                )
            return

        if isinstance(event, Notice) and event.message:
            await self._emit_to_session(cid, {"type": "token.delta", "payload": {"text": f"\n{event.message}\n"}})

    async def _on_spine_event(self, event: TurnEvent) -> None:
        if isinstance(event, TurnStarted):
            sub_id = self._turn_submissions.get((event.conversation_id, event.turn_id), event.turn_id)
            self._latest_turn_by_cid[event.conversation_id] = event.turn_id
            await self._emit_to_session(
                event.conversation_id,
                {
                    "type": "message.start",
                    "payload": {
                        "submission_id": sub_id,
                        "turn_id": event.turn_id,
                    },
                },
            )
            return

        if isinstance(event, TurnEnded):
            cid = event.conversation_id
            sub_id = self._turn_submissions.pop((cid, event.turn_id), event.turn_id)
            self._active_handles.pop(cid, None)
            self._inflight_tools.pop(cid, None)
            # 保留会话标题等元数据，避免 Lane 保存时覆盖 title
            entry = self._ensure_session_entry(cid)
            saved = self.session_manager.load(cid)
            if saved is not None and entry.get("title"):
                extra = {**saved.metadata.extra, "title": entry["title"]}
                self.session_manager.save(cid, saved.messages, extra=extra)

            if event.turn_id not in self._emitted_text_turns and event.final_content:
                await self._emit_to_session(cid, {"type": "token.delta", "payload": {"text": event.final_content}})
            self._emitted_text_turns.discard(event.turn_id)

            from orangecode.call_efficiency.pricing import calculate_call_cost
            from orangecode.utils.token_counter import estimate_prompt_tokens

            prev = self._usage_for(cid)
            prompt_tok = int(event.usage.prompt_tokens)
            comp_tok = int(event.usage.completion_tokens)
            total_tok = int(event.usage.total_tokens or (prompt_tok + comp_tok))
            turn_cost = calculate_call_cost(self.config_store.model, prompt_tok, comp_tok)

            ctx_used = total_tok
            if saved and saved.messages:
                ctx_used = max(ctx_used, estimate_prompt_tokens(saved.messages))
            ctx_pct = min(100, round(ctx_used / DEFAULT_CONTEXT_MAX * 100, 1)) if DEFAULT_CONTEXT_MAX else 0

            new_usage = {
                "calls": prev["calls"] + 1,
                "input": prev["input"] + prompt_tok,
                "output": prev["output"] + comp_tok,
                "total": prev["total"] + total_tok,
                "context_used": ctx_used,
                "context_max": DEFAULT_CONTEXT_MAX,
                "context_percent": ctx_pct,
                "cost_usd": round(float(prev.get("cost_usd", 0.0)) + turn_cost, 6),
            }
            self._session_usage[cid] = new_usage

            await self._emit_to_session(
                cid,
                {
                    "type": "message.complete",
                    "payload": {
                        "submission_id": sub_id,
                        "turn_id": event.turn_id,
                        "usage": {
                            "prompt_tokens": prompt_tok,
                            "completion_tokens": comp_tok,
                            "total_tokens": total_tok,
                            **new_usage,
                        },
                    },
                },
            )
            return

        if isinstance(event, TurnFailed):
            cid = event.conversation_id
            sub_id = self._turn_submissions.pop((cid, event.turn_id), event.turn_id)
            self._active_handles.pop(cid, None)
            self._inflight_tools.pop(cid, None)
            self._emitted_text_turns.discard(event.turn_id)
            cancelled = "cancelled" in event.error.lower() or "interrupted" in event.error.lower()
            await self._emit_to_session(
                cid,
                {
                    "type": "error",
                    "payload": {
                        "submission_id": sub_id,
                        "turn_id": event.turn_id,
                        "code": -32000,
                        "message": event.error,
                        "reason": "cancelled_by_client" if cancelled else "internal",
                    },
                },
            )

    async def _emit_missing_credentials_error(self, sid: str, submission_id: str, turn_id: str) -> None:
        await asyncio.sleep(0)
        await self._emit_to_session(
            sid,
            {
                "type": "message.start",
                "payload": {"submission_id": submission_id, "turn_id": turn_id},
            },
        )
        await self._emit_to_session(
            sid,
            {
                "type": "error",
                "payload": {
                    "submission_id": submission_id,
                    "turn_id": turn_id,
                    "code": ERR_MODEL_NOT_AVAILABLE,
                    "message": (
                        f"No API key configured for '{self.config_store.provider}'. "
                        "Run /model in TUI or export ORANGECODE_API_KEY before chatting."
                    ),
                    "reason": "internal",
                },
            },
        )

    # ── RPC 方法注册 ──────────────────────────────────────────────────

    def _register_default_methods(self) -> None:
        self._register_system_methods()
        self._register_session_methods()
        self._register_turn_methods()
        self._register_model_and_config_methods()
        self._register_broker_methods()

    def _register_system_methods(self) -> None:
        async def system_hello(params: dict[str, Any]) -> dict[str, Any]:
            recent = self.session_manager.list_sessions()
            default_key = recent[0].conversation_id if recent else f"tui:{uuid4().hex[:8]}"
            return {
                "server_version": __version__,
                "server_capabilities": ["chat", "config", "confirm", "clarify", "sessions", "models"],
                "session": {
                    "default_channel": "tui",
                    "default_session_key": default_key,
                },
            }

        async def system_ping(params: dict[str, Any]) -> dict[str, Any]:
            return {
                "pong": True,
                "server_time_ms": int(time.time() * 1000),
                "status": "pong",
                "version": __version__,
            }

        async def system_version(params: dict[str, Any]) -> dict[str, Any]:
            return {
                "server_version": __version__,
                "schema_version": "0.1.0",
                "orangecode_version": __version__,
            }

        async def setup_status(params: dict[str, Any]) -> dict[str, Any]:
            # 允许无 key 先进入主界面，在 SessionInfo 中通过 credential_warning 温和提醒并支持 /model 配置
            return {"provider_configured": True}

        async def terminal_resize(params: dict[str, Any]) -> dict[str, Any]:
            cols = int(params.get("cols") or self._terminal_size[0])
            rows = int(params.get("rows") or self._terminal_size[1])
            self._terminal_size = (max(20, cols), max(10, rows))
            return {"ok": True}

        self.dispatcher.register("system.hello", system_hello)
        self.dispatcher.register("system.ping", system_ping)
        self.dispatcher.register("system/ping", system_ping)
        self.dispatcher.register("system.version", system_version)
        self.dispatcher.register("setup.status", setup_status)
        self.dispatcher.register("terminal.resize", terminal_resize)

    def _register_session_methods(self) -> None:
        async def session_list(params: dict[str, Any]) -> dict[str, Any]:
            limit = int(params.get("limit") or 200)
            sessions = self.session_manager.list_sessions()[:limit]
            rows: list[dict[str, Any]] = []
            for meta in sessions:
                record = self.session_manager.load(meta.conversation_id)
                preview = _session_preview(record.messages) if record else ""
                title = str(meta.extra.get("title") or preview or meta.conversation_id)
                rows.append(
                    {
                        "id": meta.conversation_id,
                        "conversation_id": meta.conversation_id,
                        "title": title,
                        "preview": preview,
                        "message_count": meta.message_count,
                        "started_at": _iso_to_unix_ts(meta.created_at),
                        "created_at": meta.created_at,
                        "updated_at": meta.updated_at,
                        "source": "tui",
                    }
                )
            return {"sessions": rows}

        async def session_create(params: dict[str, Any]) -> dict[str, Any]:
            if params.get("cols"):
                self._terminal_size = (int(params["cols"]), self._terminal_size[1])
            sid = f"tui:{uuid4().hex[:8]}"
            self._sessions[sid] = {"title": "", "created_at": time.time()}
            return {"session_id": sid, "info": self._build_session_info(sid)}

        async def session_most_recent(params: dict[str, Any]) -> dict[str, Any]:
            sessions = self.session_manager.list_sessions()
            if not sessions:
                return {"session_id": None}
            top = sessions[0]
            return {
                "session_id": top.conversation_id,
                "source": "tui",
                "started_at": _iso_to_unix_ts(top.created_at),
                "title": str(top.extra.get("title") or top.conversation_id),
            }

        async def session_resume(params: dict[str, Any]) -> dict[str, Any]:
            sid = str(params.get("session_id") or "").strip()
            if not sid:
                raise RpcMethodError(ERR_CONFIG_VALIDATION, "Missing session_id")
            record = self._load_or_error(sid)
            self._sessions[sid] = {
                "title": str(record.metadata.extra.get("title") or ""),
                "created_at": _iso_to_unix_ts(record.metadata.created_at),
            }
            self._sync_lane_history(sid, record.messages)
            return {
                "session_id": record.metadata.conversation_id,
                "resumed": record.metadata.conversation_id,
                "message_count": len(record.messages),
                "info": self._build_session_info(sid),
                "messages": _to_transcript_messages(record.messages),
            }

        async def session_close(params: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        async def session_delete(params: dict[str, Any]) -> dict[str, Any]:
            sid = str(params.get("session_id") or "").strip()
            if not sid:
                return {"deleted": None}
            self._sessions.pop(sid, None)
            self._session_usage.pop(sid, None)
            if self.scheduler:
                self.scheduler._lanes.pop(sid, None)
            deleted = self.session_manager.delete(sid)
            return {"deleted": sid if deleted else None}

        async def session_title(params: dict[str, Any]) -> dict[str, Any]:
            sid = str(params.get("session_id") or "").strip()
            title = str(params.get("title") or "").strip()
            if not sid:
                raise RpcMethodError(ERR_CONFIG_VALIDATION, "Missing session_id")
            entry = self._ensure_session_entry(sid)
            entry["title"] = title
            record = self.session_manager.load(sid)
            pending = record is None
            if record is not None:
                extra = {**record.metadata.extra, "title": title}
                self.session_manager.save(sid, record.messages, extra=extra)
            return {"title": title, "session_key": sid, "pending": pending}

        async def session_clear(params: dict[str, Any]) -> dict[str, Any]:
            sid = str(params.get("session_id") or "").strip()
            if not sid:
                raise RpcMethodError(ERR_CONFIG_VALIDATION, "Missing session_id")
            entry = self._ensure_session_entry(sid)
            self.session_manager.save(sid, [], extra={"title": entry.get("title", "")})
            self._sync_lane_history(sid, [])
            self._session_usage.pop(sid, None)
            return {"session_id": sid, "cleared": True}

        async def session_undo(params: dict[str, Any]) -> dict[str, Any]:
            sid = str(params.get("session_id") or "").strip()
            n_turns = max(1, int(params.get("n") or 1))
            record = self.session_manager.load(sid)
            if record is None or not record.messages:
                return {"removed": 0}
            msgs = list(record.messages)
            removed = 0
            for _ in range(n_turns):
                user_indices = [i for i, m in enumerate(msgs) if m.get("role") == "user"]
                if not user_indices:
                    break
                cut = user_indices[-1]
                removed += len(msgs) - cut
                msgs = msgs[:cut]
            if removed:
                self.session_manager.save(sid, msgs, extra=record.metadata.extra)
                self._sync_lane_history(sid, msgs)
            return {"removed": removed}

        async def session_branch(params: dict[str, Any]) -> dict[str, Any]:
            sid = str(params.get("session_id") or "").strip()
            name = str(params.get("name") or "").strip()
            if not sid:
                raise RpcMethodError(ERR_CONFIG_VALIDATION, "Missing session_id")
            slug = "".join(c for c in name if c.isalnum() or c in ("-", "_")) if name else uuid4().hex[:8]
            target_id = f"tui:{slug or uuid4().hex[:8]}"
            src = self._load_or_error(sid)
            forked = self.session_manager.save(
                target_id,
                list(src.messages),
                extra={"forked_from": sid, "title": name or target_id},
            )
            self._sessions[target_id] = {"title": name or target_id, "created_at": time.time()}
            return {
                "session_id": forked.metadata.conversation_id,
                "title": name or forked.metadata.conversation_id,
                "message_count": forked.metadata.message_count,
            }

        async def session_export(params: dict[str, Any]) -> dict[str, Any]:
            from orangecode.session.export import export_session_to_file

            sid = str(params.get("session_id") or "").strip()
            record = self.session_manager.load(sid)
            if record is None:
                return {"exported": False, "reason": "not_found"}
            safe = "".join(c for c in sid if c.isalnum() or c in ("-", "_")) or "session"
            dest = self.session_manager.base_dir.parent / "exports" / f"{safe}-{int(time.time())}.md"
            written = export_session_to_file(record, dest)
            return {"exported": True, "path": str(written)}

        self.dispatcher.register("session.list", session_list)
        self.dispatcher.register("session/list", session_list)
        self.dispatcher.register("session.create", session_create)
        self.dispatcher.register("session.most_recent", session_most_recent)
        self.dispatcher.register("session.resume", session_resume)
        self.dispatcher.register("session.close", session_close)
        self.dispatcher.register("session.delete", session_delete)
        self.dispatcher.register("session.title", session_title)
        self.dispatcher.register("session.clear", session_clear)
        self.dispatcher.register("session.undo", session_undo)
        self.dispatcher.register("session.branch", session_branch)
        self.dispatcher.register("session.export", session_export)

    def _register_turn_methods(self) -> None:
        async def turn_subscribe(params: dict[str, Any]) -> dict[str, Any]:
            session_key = str(params.get("session_key") or "default_tui")
            sub_id = f"sub_{uuid4().hex[:12]}"
            self._subscriptions[sub_id] = session_key
            return {"subscription_id": sub_id}

        async def turn_unsubscribe(params: dict[str, Any]) -> dict[str, Any]:
            sub_id = str(params.get("subscription_id") or "")
            removed = self._subscriptions.pop(sub_id, None) is not None
            return {"unsubscribed": removed}

        async def turn_send(params: dict[str, Any]) -> dict[str, Any]:
            if not self.scheduler:
                raise RuntimeError("SpineScheduler not attached to RPC server.")
            session_key = str(params.get("session_key") or "default_tui")
            content = str(params.get("content") or "")
            submission_id = str(params.get("submission_id") or uuid4().hex)

            if self._owns_scheduler:
                api_key, _ = self.config_store.resolve_credentials()
                local_prefix = self.config_store.model.lower().startswith(("ollama/", "lm_studio/", "vllm/"))
                if not api_key and not local_prefix:
                    turn_id = f"turn_{uuid4().hex[:8]}"
                    asyncio.create_task(self._emit_missing_credentials_error(session_key, submission_id, turn_id))
                    return {"turn_id": turn_id, "accepted": True}

            handle = self.scheduler.submit(
                TurnRequest(
                    prompt=content,
                    conversation_id=session_key,
                    origin=Origin.USER,
                    busy_policy=BusyPolicy.APPEND,
                )
            )
            self._turn_submissions[(session_key, handle.turn_id)] = submission_id
            self._active_handles[session_key] = handle
            return {"turn_id": handle.turn_id, "accepted": True}

        async def turn_cancel(params: dict[str, Any]) -> dict[str, Any]:
            session_key = str(params.get("session_key") or "default_tui")
            handle = self._active_handles.get(session_key)
            if not handle:
                return {"cancelled": False}
            return {"cancelled": bool(handle.cancel())}

        async def turn_submit_legacy(params: dict[str, Any]) -> dict[str, Any]:
            if not self.scheduler:
                raise RuntimeError("SpineScheduler not attached to RPC server.")
            prompt = str(params.get("prompt") or "")
            cid = str(params.get("conversation_id") or "default_tui")
            policy_str = str(params.get("busy_policy") or "append")
            policy = BusyPolicy.APPEND
            if policy_str == "interrupt":
                policy = BusyPolicy.INTERRUPT
            elif policy_str == "inject":
                policy = BusyPolicy.INJECT
            handle = self.scheduler.submit(
                TurnRequest(prompt=prompt, conversation_id=cid, origin=Origin.USER, busy_policy=policy)
            )
            return {"turn_id": handle.turn_id, "conversation_id": cid}

        self.dispatcher.register("turn.subscribe", turn_subscribe)
        self.dispatcher.register("turn.unsubscribe", turn_unsubscribe)
        self.dispatcher.register("turn.send", turn_send)
        self.dispatcher.register("turn.cancel", turn_cancel)
        self.dispatcher.register("turn/submit", turn_submit_legacy)

    def _register_model_and_config_methods(self) -> None:
        async def model_options(params: dict[str, Any]) -> dict[str, Any]:
            return self.config_store.model_options()

        async def model_save_key(params: dict[str, Any]) -> dict[str, Any]:
            slug = str(params.get("slug") or "")
            api_key = str(params.get("api_key") or "")
            api_base = params.get("api_base")
            try:
                return self.config_store.save_key(slug, api_key, str(api_base) if api_base else None)
            except (KeyError, ValueError) as exc:
                raise RpcMethodError(ERR_CONFIG_VALIDATION, str(exc)) from exc

        async def model_add_model(params: dict[str, Any]) -> dict[str, Any]:
            try:
                return self.config_store.add_model(str(params.get("slug") or ""), str(params.get("model") or ""))
            except (KeyError, ValueError) as exc:
                raise RpcMethodError(ERR_CONFIG_VALIDATION, str(exc)) from exc

        async def model_remove_model(params: dict[str, Any]) -> dict[str, Any]:
            try:
                return self.config_store.remove_model(str(params.get("slug") or ""), str(params.get("model") or ""))
            except (KeyError, ValueError) as exc:
                raise RpcMethodError(ERR_CONFIG_VALIDATION, str(exc)) from exc

        async def model_disconnect(params: dict[str, Any]) -> dict[str, Any]:
            return self.config_store.disconnect(str(params.get("slug") or ""))

        async def config_get(params: dict[str, Any]) -> dict[str, Any]:
            snap = self.config_store.snapshot()
            keys = params.get("keys")
            if isinstance(keys, list) and keys:
                snap = {k: snap[k] for k in keys if k in snap}
            return {"config": snap}

        async def config_set(params: dict[str, Any]) -> dict[str, Any]:
            key = str(params.get("key") or "").strip()
            value = params.get("value")
            provider = params.get("provider")
            sid = str(params.get("session_id") or "")
            if not key:
                raise RpcMethodError(ERR_CONFIG_VALIDATION, "Config key cannot be empty")
            if key == "model":
                if not isinstance(value, str) or not value.strip():
                    raise RpcMethodError(ERR_CONFIG_VALIDATION, "Model value must be a non-empty string")
                prev = self.config_store.set_active_model(value, str(provider) if provider else None)
                return {
                    "applied": True,
                    "previous": prev,
                    "value": self.config_store.model,
                    "info": self._build_session_info(sid),
                }
            if key == "reasoning_effort":
                prev = self.config_store.set_reasoning_effort(str(value) if value is not None else None)
                return {"applied": True, "previous": prev, "value": self.config_store.reasoning_effort or ""}
            raise RpcMethodError(ERR_CONFIG_READONLY, f"Config key '{key}' is not writable at runtime")

        async def image_attach(params: dict[str, Any]) -> dict[str, Any]:
            raise RpcMethodError(ERR_NOT_SUPPORTED, "Image attachments are not supported yet in OrangeCode backend")

        self.dispatcher.register("model.options", model_options)
        self.dispatcher.register("model.save_key", model_save_key)
        self.dispatcher.register("model.add_model", model_add_model)
        self.dispatcher.register("model.remove_model", model_remove_model)
        self.dispatcher.register("model.disconnect", model_disconnect)
        self.dispatcher.register("config.get", config_get)
        self.dispatcher.register("config.set", config_set)
        self.dispatcher.register("image.attach", image_attach)

    def _register_broker_methods(self) -> None:
        async def confirm_respond(params: dict[str, Any]) -> dict[str, Any]:
            request_id = str(params.get("request_id") or "")
            answer = bool(params.get("answer", False))
            ok = self.confirm_broker.resolve(request_id, answer)
            return {"ok": ok, "accepted": ok, "request_id": request_id}

        async def clarify_respond(params: dict[str, Any]) -> dict[str, Any]:
            key = params.get("key") or params.get("request_id") or params.get("conversation_id") or ""
            answer = str(params.get("answer", ""))
            ok = self.question_broker.reply(str(key), answer)
            return {"ok": ok, "accepted": ok, "key": key}

        self.dispatcher.register("confirm.respond", confirm_respond)
        self.dispatcher.register("confirm/respond", confirm_respond)
        self.dispatcher.register("clarify.respond", clarify_respond)
        self.dispatcher.register("question/respond", clarify_respond)

    # ── JSON 行分发与 TCP Socket 服务循环 ─────────────────────────────

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

        if not isinstance(req_frame, dict):
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Request frame must be a JSON object."},
            }
            return json.dumps(err_resp, ensure_ascii=False)

        resp_frame = await self.dispatcher.dispatch(req_frame)
        return json.dumps(resp_frame, ensure_ascii=False)

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        logger.debug(f"TUI RPC client connected: {peer}")
        self._active_writer = writer

        async def _dispatch_and_send(raw_line: str) -> None:
            resp_str = await self.handle_json_line(raw_line)
            if not resp_str:
                return
            data = (resp_str + "\n").encode("utf-8")
            async with self._write_lock:
                if self._active_writer is writer and not writer.is_closing():
                    writer.write(data)
                    await writer.drain()

        try:
            # 1. 若启用共享密钥，首行必须是 ORANGECODE_RPC_TOKEN
            if self.auth_token:
                raw_token = await asyncio.wait_for(reader.readline(), timeout=5.0)
                token_line = raw_token.decode("utf-8", errors="replace").rstrip("\r\n")
                if not raw_token or not hmac.compare_digest(token_line, self.auth_token):
                    logger.warning("TUI RPC connection rejected: invalid or missing auth token")
                    return

            # 2. 逐行读取 NDJSON 帧并并发派发，确保 clarify/confirm/cancel 不被阻塞
            while not self._closed:
                raw = await reader.readline()
                if not raw:
                    break
                if len(raw) > MAX_FRAME_BYTES:
                    logger.warning(f"Dropping oversized RPC frame ({len(raw)} bytes)")
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                task = asyncio.create_task(_dispatch_and_send(line))
                self._conn_tasks.add(task)
                task.add_done_callback(self._conn_tasks.discard)
        except asyncio.CancelledError:
            pass
        except Exception as err:
            logger.exception(f"TUI RPC socket loop error: {err}")
        finally:
            if self._active_writer is writer:
                self._active_writer = None
            for task in list(self._conn_tasks):
                task.cancel()
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.debug(f"TUI RPC client disconnected: {peer}")

    async def start_tcp(self, host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
        """启动本地回环 TCP JSON-RPC 服务器并返回实际绑定的 (host, port)。"""
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=host,
            port=port,
            limit=MAX_FRAME_BYTES,
        )
        sock = self._server.sockets[0]
        bound_host, bound_port = sock.getsockname()[:2]
        logger.info(f"TuiRpcServer listening on {bound_host}:{bound_port}")
        return str(bound_host), int(bound_port)

    async def aclose(self) -> None:
        """异步关闭套接字服务、调度器与挂起交互。"""
        self.close()
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        if self._owns_scheduler and self.scheduler is not None:
            await self.scheduler.shutdown()

    def close(self) -> None:
        """服务关闭时安全收敛未决交互。"""
        self._closed = True
        self.confirm_broker.cancel_all()
        self.question_broker.cancel_all()
