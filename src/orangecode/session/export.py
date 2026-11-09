"""会话导出器：渲染为高保真 Markdown 轨迹或可自校验的 JSON 信封。"""

import hashlib
import json
from pathlib import Path

from orangecode.session.manager import SessionRecord

_ROLE_HEADINGS = {
    "user": "## 🧑 User",
    "assistant": "## 🤖 Assistant",
    "system": "## ⚙️ System",
    "tool": "## 🛠 Tool Result",
}
_EXPORT_SCHEMA = "orangecode.session.export.v1"


def render_transcript(record: SessionRecord) -> str:
    """将会话记录渲染为排版清晰的 Markdown 文档。"""
    meta = record.metadata
    parts: list[str] = [
        f"# Session Transcript: `{meta.conversation_id}`",
        f"- **Created At**: {meta.created_at}",
        f"- **Last Updated**: {meta.updated_at}",
        f"- **Message Count**: {meta.message_count}",
        "---\n",
    ]

    for msg in record.messages:
        role = msg.get("role", "unknown")
        heading = _ROLE_HEADINGS.get(role, f"## {role.title()}")
        parts.append(heading)

        content = msg.get("content")
        if content:
            parts.append(str(content).strip())

        # 呈现工具调用
        tool_calls = msg.get("tool_calls")
        if tool_calls and isinstance(tool_calls, list):
            parts.append("\n**Tool Calls:**")
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "unknown_tool")
                args = fn.get("arguments", "{}")
                parts.append(f"- `{name}` with arguments: `{args}`")

        parts.append("")  # 换行

    return "\n\n".join(parts)


def export_session_to_file(record: SessionRecord, dest: Path) -> Path:
    """将会话记录导出为文件（支持 .md 与可校验的 .json 两种格式）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    markdown_str = render_transcript(record)

    if dest.suffix.lower() == ".md":
        dest.write_text(markdown_str, encoding="utf-8")
        return dest

    # 导出可验证的 JSON 信封
    canonical_payload = json.dumps(
        {
            "metadata": {
                "conversation_id": record.metadata.conversation_id,
                "created_at": record.metadata.created_at,
                "updated_at": record.metadata.updated_at,
                "message_count": record.metadata.message_count,
            },
            "messages": record.messages,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    envelope = {
        "schema": _EXPORT_SCHEMA,
        "conversation_id": record.metadata.conversation_id,
        "sha256": digest,
        "payload": json.loads(canonical_payload),
        "transcript_markdown": markdown_str,
    }

    dest.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def verify_export(export_path: Path) -> bool:
    """验证导出文件的 SHA-256 完整性校验和。"""
    try:
        data = json.loads(export_path.read_text(encoding="utf-8"))
        if data.get("schema") != _EXPORT_SCHEMA:
            return False
        expected_digest = data.get("sha256", "")
        payload = data.get("payload", {})
        canonical_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        actual_digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
        return actual_digest == expected_digest
    except Exception:
        return False
