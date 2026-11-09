"""Token 数量精确与容错估算模块。"""

import json
from typing import Any

import tiktoken


def _message_token_parts(msg: dict[str, Any]) -> list[str]:
    """提取单条消息中所有会被计入 Token 的文本部分。"""
    parts: list[str] = []
    role = msg.get("role", "")
    if role:
        parts.append(str(role))

    content = msg.get("content")
    if content:
        parts.append(str(content))

    tool_calls = msg.get("tool_calls")
    if tool_calls and isinstance(tool_calls, list):
        for tc in tool_calls:
            if isinstance(tc, dict):
                parts.append(json.dumps(tc, ensure_ascii=False))

    name = msg.get("name")
    if name:
        parts.append(str(name))

    tool_call_id = msg.get("tool_call_id")
    if tool_call_id:
        parts.append(str(tool_call_id))

    return parts


def estimate_prompt_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    encoding_name: str = "cl100k_base",
) -> int:
    """使用 Tiktoken 估算完整 Prompt 的 Tokens 总数。

    如果 Tiktoken 无法加载或发生异常，则按中英文混合平均 4 个字符 ≈ 1 Token 回退。
    """
    parts: list[str] = []
    for msg in messages:
        parts.extend(_message_token_parts(msg))

    if tools:
        parts.append(json.dumps(tools, ensure_ascii=False))

    payload = "\n".join(parts)
    if not payload:
        return 0

    try:
        enc = tiktoken.get_encoding(encoding_name)
        return max(1, len(enc.encode(payload)))
    except Exception:
        # 兜底回退：按字符数粗略折算
        return max(1, len(payload) // 4)


def estimate_message_tokens(message: dict[str, Any], encoding_name: str = "cl100k_base") -> int:
    """估算单条消息所占用的 Token 数量。"""
    return estimate_prompt_tokens([message], encoding_name=encoding_name)
