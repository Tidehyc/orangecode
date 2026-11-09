"""外部消息渠道契约模型：统一入站与出站载荷规范。"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ChannelType(StrEnum):
    """支持的外部消息渠道类型。"""

    FEISHU = "feishu"
    WECOM = "wecom"
    QQ = "qq"
    CLI = "cli"
    WEBHOOK = "webhook"


@dataclass(frozen=True)
class InboundMessage:
    """来自外部渠道的标准入站消息封装。"""

    channel_type: ChannelType
    chat_id: str
    sender_id: str
    text: str
    message_id: str | None = None
    media_urls: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def conversation_id(self) -> str:
        """根据渠道类型与聊天 ID 构造标准化的会话键（如 feishu:oc_123456）。"""
        return f"{self.channel_type}:{self.chat_id}"


@dataclass(frozen=True)
class OutboundMessage:
    """回复给外部渠道的标准出站消息。"""

    channel_type: ChannelType
    chat_id: str
    text: str
    reply_to: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
