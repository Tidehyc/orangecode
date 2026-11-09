"""企业微信 (WeCom) 消息渠道适配器。"""

from typing import Any

import httpx
from loguru import logger

from orangecode.channels.base import BaseChannel
from orangecode.channels.contract import ChannelType, InboundMessage, OutboundMessage


class WeComChannel(BaseChannel):
    """企业微信机器人适配器。"""

    channel_type = ChannelType.WECOM

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = webhook_url

    @staticmethod
    def parse_webhook_payload(payload: dict[str, Any]) -> InboundMessage | None:
        """解析企微机器人回调数据包。"""
        content = payload.get("text", {}).get("content", "")
        sender = payload.get("from", {}).get("alias", "unknown_wecom_user")
        chat_id = payload.get("chatid", "default_wecom_chat")

        return InboundMessage(
            channel_type=ChannelType.WECOM,
            chat_id=chat_id,
            sender_id=sender,
            text=content,
            message_id=payload.get("msgid"),
            raw_payload=payload,
        )

    async def send_message(self, message: OutboundMessage) -> bool:
        """向企业微信群机器人投递 Markdown 消息。"""
        if self.webhook_url:
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": message.text},
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(self.webhook_url, json=payload)
                    return resp.status_code == 200
            except Exception as e:
                logger.error(f"Failed to post to WeCom webhook: {e}")
                return False

        logger.info(f"[WeCom Mock Send] To {message.chat_id}: {message.text[:100]}...")
        return True
