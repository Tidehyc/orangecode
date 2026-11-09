"""渠道管理器：负责将外部入站消息与 Spine 调度总线双向打通。"""

from loguru import logger

from orangecode.channels.base import BaseChannel
from orangecode.channels.contract import ChannelType, InboundMessage, OutboundMessage
from orangecode.spine.events import TurnEnded, TurnEvent
from orangecode.spine.scheduler import SpineScheduler
from orangecode.spine.turn import BusyPolicy, Origin, TurnHandle, TurnRequest


class ChannelManager:
    """多渠道中枢路由器。"""

    def __init__(self, scheduler: SpineScheduler) -> None:
        self.scheduler = scheduler
        self._channels: dict[ChannelType, BaseChannel] = {}

    def register_channel(self, channel: BaseChannel) -> None:
        """注册具体渠道适配器。"""
        self._channels[channel.channel_type] = channel
        logger.info(f"Registered channel adapter: {channel.channel_type}")

    def get_channel(self, ctype: ChannelType) -> BaseChannel | None:
        return self._channels.get(ctype)

    def dispatch_inbound(self, msg: InboundMessage) -> TurnHandle:
        """接收外部消息，转换并提交给 Spine 调度器执行。"""
        logger.info(f"Inbound message from [{msg.conversation_id}]: {msg.text[:60]}...")
        req = TurnRequest(
            prompt=msg.text,
            conversation_id=msg.conversation_id,
            origin=Origin.USER,
            busy_policy=BusyPolicy.APPEND,
            metadata={"source_message_id": msg.message_id},
        )
        return self.scheduler.submit(req)

    async def on_spine_event(self, event: TurnEvent) -> None:
        """接收 Spine 产生的生命周期事件，如果是 TurnEnded 则自动回传结果给外部渠道。"""
        if not isinstance(event, TurnEnded):
            return

        cid = event.conversation_id
        if ":" not in cid:
            return

        channel_prefix, chat_id = cid.split(":", 1)
        try:
            ctype = ChannelType(channel_prefix)
        except ValueError:
            return

        channel = self.get_channel(ctype)
        if not channel:
            logger.warning(f"No channel registered for prefix '{channel_prefix}' to deliver reply.")
            return

        logger.info(f"Delivering Spine Turn reply to channel [{ctype}] chat [{chat_id}]...")
        outbound = OutboundMessage(
            channel_type=ctype,
            chat_id=chat_id,
            text=event.final_content,
        )
        await channel.send_message(outbound)
