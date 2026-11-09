"""负责历史消息的原子闭包、工具输出压缩与预算驱动裁剪。"""

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from orangecode.context.budget import TokenBudget
from orangecode.utils.token_counter import estimate_prompt_tokens

# 允许发送给大模型的合法字段白名单
_ALLOWED_KEYS = {
    "role",
    "content",
    "tool_calls",
    "tool_call_id",
    "name",
    "reasoning_content",
}


@dataclass
class TrimOutcome:
    """记录一次历史裁剪的决策与 Token 账本。"""

    messages: list[dict[str, Any]]
    estimated_tokens: int
    max_tokens: int
    dropped_turns_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """最终 Prompt 是否成功收敛在预算上限之内。"""
        return self.estimated_tokens <= self.max_tokens


class HistoryTrimmer:
    """保证多轮会话结构合法并符合 Token 预算的裁剪器。"""

    def __init__(self, budget: TokenBudget | None = None) -> None:
        self.budget = budget or TokenBudget()

    @staticmethod
    def canonical_ids(messages: list[dict[str, Any]], ids: list[int]) -> list[int]:
        """计算 Tool Call 与 Tool Result 的传递闭包，确保工具调用原子性。

        如果选择了 assistant(tool_calls)，必须带上所有对应的 tool(result)；
        如果选中了某个 tool(result)，必须向上带回其父 assistant(tool_calls)。
        同时保证裁剪后的历史必须以第一个 user 消息开始，不会以断头的 tool 结果起头。
        """
        valid_ids = {i for i in ids if 0 <= i < len(messages)}
        tool_parent_by_call: dict[str, int] = {}
        tool_results_by_call: dict[str, list[int]] = {}

        for idx, msg in enumerate(messages):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        tool_parent_by_call[str(tc["id"])] = idx
            if msg.get("role") == "tool" and msg.get("tool_call_id"):
                cid = str(msg["tool_call_id"])
                tool_results_by_call.setdefault(cid, []).append(idx)

        # 闭包扩散直到稳定
        changed = True
        while changed:
            changed = False
            for call_id, parent_idx in tool_parent_by_call.items():
                results = tool_results_by_call.get(call_id, [])
                # 父在 -> 子全进
                if parent_idx in valid_ids:
                    for rid in results:
                        if rid not in valid_ids:
                            valid_ids.add(rid)
                            changed = True
                # 子在 -> 父必须进
                if any(rid in valid_ids for rid in results) and parent_idx not in valid_ids:
                    valid_ids.add(parent_idx)
                    changed = True

        ordered = sorted(valid_ids)
        # 寻找第一个 user 消息作为合法开端
        for pos, mid in enumerate(ordered):
            if messages[mid].get("role") == "user":
                return ordered[pos:]
        return []

    @staticmethod
    def structural_errors(messages: list[dict[str, Any]]) -> list[str]:
        """验证消息列表中是否存在悬空的 Tool Call 或无父级孤儿 Tool Result。"""
        errors: list[str] = []
        open_calls: set[str] = set()

        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        open_calls.add(str(tc["id"]))
            if msg.get("role") == "tool":
                call_id = str(msg.get("tool_call_id", ""))
                if call_id not in open_calls:
                    errors.append(f"Tool result {call_id} has no parent assistant tool_call")
                else:
                    open_calls.remove(call_id)

        if open_calls:
            errors.append(f"Assistant tool_calls missing results: {sorted(open_calls)}")
        return errors

    @staticmethod
    def compact_tool_results(
        messages: list[dict[str, Any]],
        max_chars: int = 1500,
        keep_recent_turns: int = 1,
    ) -> list[dict[str, Any]]:
        """对历史较早轮次中过长的工具输出（如大文件或 shell 日志）进行折叠压缩。"""
        # 计算 user 消息的位置作为轮次标记
        user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        cutoff_idx = user_indices[-keep_recent_turns] if len(user_indices) >= keep_recent_turns else 0

        compacted: list[dict[str, Any]] = []
        for idx, msg in enumerate(messages):
            new_msg = dict(msg)
            # 仅压缩 cutoff_idx 之前的旧轮次中的 tool 结果
            if idx < cutoff_idx and new_msg.get("role") == "tool":
                content = str(new_msg.get("content") or "")
                if len(content) > max_chars:
                    head_size = max_chars // 2
                    tail_size = max_chars // 3
                    omitted = len(content) - head_size - tail_size
                    new_msg["content"] = (
                        f"{content[:head_size]}\n\n"
                        f"[... Output truncated ({omitted} characters omitted) ...]\n\n"
                        f"{content[-tail_size:]}"
                    )
            compacted.append(new_msg)
        return compacted

    def sanitize(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """过滤非标准字段，仅保留大模型供应商认可的消息字段。"""
        cleaned: list[dict[str, Any]] = []
        for msg in messages:
            clean = {k: v for k, v in msg.items() if k in _ALLOWED_KEYS}
            if clean.get("role"):
                cleaned.append(clean)
        return cleaned

    def trim(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        protected_user_count: int = 1,
    ) -> TrimOutcome:
        """执行完整上下文预算治理：清洗 -> 工具压缩 -> 按整轮闭包裁剪超限历史。"""
        if not messages:
            return TrimOutcome(messages=[], estimated_tokens=0, max_tokens=self.budget.max_prompt_tokens)

        # 1. 字段清洗
        working_messages = self.sanitize(messages)

        # 2. 对旧轮次工具输出进行压缩
        working_messages = self.compact_tool_results(working_messages)

        # 3. 提取所有索引
        ids = list(range(len(working_messages)))
        canonical_active_ids = self.canonical_ids(working_messages, ids)

        # 分离出 system prompt 与普通历史
        system_msg: dict[str, Any] | None = None
        if working_messages and working_messages[0].get("role") == "system":
            system_msg = working_messages[0]

        # 4. 按 User 消息切分轮次组 (Turn Groups)
        # 每个 Turn Group 包含一个 User 消息及其后续的 Assistant / Tool 调用
        turn_groups: list[list[int]] = []
        current_group: list[int] = []
        for mid in canonical_active_ids:
            if working_messages[mid].get("role") == "user" and current_group:
                turn_groups.append(current_group)
                current_group = []
            current_group.append(mid)
        if current_group:
            turn_groups.append(current_group)

        # 5. 循环裁剪直到 Token 符合预算
        warnings: list[str] = []
        dropped_turns = 0
        max_prompt = self.budget.max_prompt_tokens

        def _build_candidate(selected_groups: list[list[int]]) -> list[dict[str, Any]]:
            flat_ids: list[int] = []
            for g in selected_groups:
                flat_ids.extend(g)
            closure_ids = self.canonical_ids(working_messages, flat_ids)
            history_subset = [working_messages[i] for i in closure_ids]
            if system_msg:
                return [system_msg, *history_subset]
            return history_subset

        current_candidate = _build_candidate(turn_groups)
        current_tokens = estimate_prompt_tokens(current_candidate, tools=tools)

        # 当超出预算且可裁剪的轮次数 > 受保护的最新轮次数时，逐轮从最旧丢弃
        while current_tokens > max_prompt and len(turn_groups) > protected_user_count:
            dropped_group = turn_groups.pop(0)
            dropped_turns += 1
            warnings.append(f"Dropped oldest turn group (indices: {dropped_group}) to satisfy token budget")
            current_candidate = _build_candidate(turn_groups)
            current_tokens = estimate_prompt_tokens(current_candidate, tools=tools)

        if current_tokens > max_prompt:
            warn = f"Prompt tokens ({current_tokens}) still exceeds budget ({max_prompt}) after dropping all unpreserved turns."
            warnings.append(warn)
            logger.warning(warn)

        return TrimOutcome(
            messages=current_candidate,
            estimated_tokens=current_tokens,
            max_tokens=max_prompt,
            dropped_turns_count=dropped_turns,
            warnings=warnings,
        )
