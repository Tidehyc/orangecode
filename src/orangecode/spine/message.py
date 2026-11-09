"""定义消息来源、附件与多模态载荷模型。"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ChatType(StrEnum):
    """会话形态：单聊与群聊。"""

    DM = "dm"
    GROUP = "group"


@dataclass(frozen=True)
class Source:
    """入站消息的来源凭据与出站回复寻址元数据。"""

    channel: str
    chat_id: str
    sender_id: str
    chat_type: ChatType = ChatType.DM
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Media:
    """多模态媒体附件描述符。"""

    path: str
    mime: str = "application/octet-stream"
    kind: str = "file"
    content: bytes | None = field(default=None, repr=False)


def safe_name(name: str | None) -> str:
    """从服务端/客户端传入的文件名中剥除路径遍历风险字符。"""
    return os.path.basename(name or "") or "file"


def save_media_bytes(dir_path: Path, data: bytes, name: str | None = None) -> Path:
    """将附件二进制安全持久化到指定目录，前缀加上内容摘要以防冲突。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:16]
    file_path = dir_path / f"{digest}_{safe_name(name)}"
    file_path.write_bytes(data)
    return file_path


def detect_image_mime(data: bytes) -> str | None:
    """基于文件 Magic Bytes 快速识别常见图片格式。"""
    if len(data) < 12:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def build_user_content(text: str, media: list[str | Media] | None = None) -> str | list[dict[str, Any]]:
    """将文本提问与媒体文件装配为 OpenAI / LiteLLM 规范的多模态 content 格式。"""
    if not media:
        return text

    images: list[dict[str, Any]] = []
    notes: list[str] = []

    for item in media:
        if isinstance(item, Media):
            p = Path(item.path)
            if item.content is not None:
                raw = item.content
                mime = detect_image_mime(raw) or item.mime
            elif p.is_file():
                raw = p.read_bytes()
                mime = detect_image_mime(raw) or item.mime
            else:
                continue
        else:
            p = Path(item)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            mime = detect_image_mime(raw) or mimetypes.guess_type(str(p))[0] or "application/octet-stream"

        if mime and mime.startswith("image/"):
            b64 = base64.b64encode(raw).decode("utf-8")
            images.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        else:
            notes.append(f"[Attachment: {p.name} (path: {p})]")

    body = text
    if notes:
        body = (f"{text}\n\n" if text else "") + "\n".join(notes)

    if not images:
        return body

    parts: list[dict[str, Any]] = list(images)
    if body:
        parts.append({"type": "text", "text": body})
    return parts
