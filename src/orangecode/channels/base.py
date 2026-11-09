"""渠道适配器抽象基类。"""

from abc import ABC, abstractmethod

from orangecode.channels.contract import ChannelType, OutboundMessage


class BaseChannel(ABC):
    """所有外部即时通讯渠道适配器的基类。"""

    channel_type: ChannelType

    @abstractmethod
    async def send_message(self, message: OutboundMessage) -> bool:
        """向外部渠道投递一条回复消息。"""
        raise NotImplementedError
