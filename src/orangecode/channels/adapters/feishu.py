"""飞书 (Feishu / Lark) 消息渠道适配器。"""

import json
from typing import Any

import httpx
from loguru import logger

from orangecode.channels.base import BaseChannel
from orangecode.channels.contract import ChannelType, InboundMessage, OutboundMessage


class FeishuChannel(BaseChannel):
    """飞书开放平台机器人适配器。"""

    channel_type = ChannelType.FEISHU

    def __init__(self, webhook_url: str | None = None, app_id: str | None = None, app_secret: str | None = None) -> None:
        self.webhook_url = webhook_url
        self.app_id = app_id
        self.app_secret = app_secret

    @staticmethod
    def parse_webhook_payload(payload: dict[str, Any]) -> InboundMessage | None:
        """解析飞书开放平台 v2 消息回调事件。"""
        event = payload.get("event", {})
        message = event.get("message", {})
        if not message:
            return None

        msg_type = message.get("message_type")
        content_str = message.get("content", "{}")
        text = ""

        if msg_type == "text":
            try:
                parsed_content = json.loads(content_str)
                text = parsed_content.get("text", "")
            except Exception:
                text = content_str
        else:
            text = f"[{msg_type} message received]"

        chat_id = message.get("chat_id", "unknown_chat")
        sender = event.get("sender", {}).get("sender_id", {}).get("open_id", "unknown_user")

        return InboundMessage(
            channel_type=ChannelType.FEISHU,
            chat_id=chat_id,
            sender_id=sender,
            text=text,
            message_id=message.get("message_id"),
            raw_payload=payload,
        )

    async def send_message(self, message: OutboundMessage) -> bool:
        """向飞书投递文本或交互卡片。"""
        if self.webhook_url:
            # 使用飞书群自定义机器人 Webhook 发送
            payload = {
                "msg_type": "text",
                "content": {"text": message.text},
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(self.webhook_url, json=payload)
                    return resp.status_code == 200
            except Exception as e:
                logger.error(f"Failed to post to Feishu webhook: {e}")
                return False

        logger.info(f"[Feishu Mock Send] To {message.chat_id}: {message.text[:100]}...")
        return True
