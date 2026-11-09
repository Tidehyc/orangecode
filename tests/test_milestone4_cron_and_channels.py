"""测试 Milestone 4：Cron 定时服务、飞书/企微渠道适配器与消息路由器。"""

import asyncio
from typing import Any

import pytest

from orangecode.agent.loop import AgentLoop
from orangecode.channels.adapters.feishu import FeishuChannel
from orangecode.channels.adapters.wecom import WeComChannel
from orangecode.channels.contract import ChannelType, InboundMessage, OutboundMessage
from orangecode.channels.manager import ChannelManager
from orangecode.proactive_engine.cron import CronService
from orangecode.providers.base import LLMProvider, LLMResponse, StreamChunk
from orangecode.spine.scheduler import SpineScheduler


class QuickMockProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__("mock")

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return LLMResponse(content=f"Echo reply to: {messages[-1]['content']}")

    async def stream_chat(self, *args, **kwargs):
        yield StreamChunk(delta_content="test")


def test_cron_service_crud(tmp_path):
    store_file = tmp_path / "test_jobs.json"
    svc = CronService(store_path=store_file)

    # 1. 成功添加任务
    job = svc.add_job(
        name="daily_summary",
        cron_expr="0 9 * * *",
        prompt="Summarize yesterday's work",
    )
    assert job.job_id.startswith("cron_")
    assert job.next_run_at > 0.0
    assert len(svc.list_jobs()) == 1

    # 2. 校验无效表达式拦截
    with pytest.raises(ValueError):
        svc.add_job(name="bad", cron_expr="invalid cron string", prompt="fail")

    # 3. 模拟到期并顺延
    job.next_run_at = 100.0  # 设为过去时间
    due = svc.check_due_jobs()
    assert len(due) == 1
    assert due[0].job_id == job.job_id
    assert due[0].next_run_at > 100.0  # 已顺延到未来

    # 4. 删除作业
    assert svc.remove_job(job.job_id)
    assert len(svc.list_jobs()) == 0


def test_feishu_and_wecom_payload_parsing():
    # 飞书回调载荷解析
    feishu_raw = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user_123"}},
            "message": {
                "message_id": "om_msg_456",
                "chat_id": "oc_chat_789",
                "message_type": "text",
                "content": '{"text": "Hello Feishu Agent"}',
            },
        }
    }
    inbound_feishu = FeishuChannel.parse_webhook_payload(feishu_raw)
    assert inbound_feishu is not None
    assert inbound_feishu.channel_type == ChannelType.FEISHU
    assert inbound_feishu.chat_id == "oc_chat_789"
    assert inbound_feishu.text == "Hello Feishu Agent"
    assert inbound_feishu.conversation_id == "feishu:oc_chat_789"

    # 企微回调载荷解析
    wecom_raw = {
        "chatid": "wecom_group_1",
        "from": {"alias": "ZhangSan"},
        "text": {"content": "Hello WeCom Bot"},
        "msgid": "msg_999",
    }
    inbound_wecom = WeComChannel.parse_webhook_payload(wecom_raw)
    assert inbound_wecom is not None
    assert inbound_wecom.channel_type == ChannelType.WECOM
    assert inbound_wecom.text == "Hello WeCom Bot"


@pytest.mark.asyncio
async def test_channel_manager_end_to_end(tmp_path):
    # 验证 Inbound 消息进 Spine，完成后的回复自动路由到对应 Channel
    sent_outbounds: list[OutboundMessage] = []

    class MockFeishuChannel(FeishuChannel):
        async def send_message(self, message: OutboundMessage) -> bool:
            sent_outbounds.append(message)
            return True

    channel_mgr_holder: list[ChannelManager] = []

    async def event_sink(evt):
        if channel_mgr_holder:
            await channel_mgr_holder[0].on_spine_event(evt)

    provider = QuickMockProvider()
    scheduler = SpineScheduler(
        agent_factory=lambda cid: AgentLoop(provider=provider),
        event_sink=event_sink,
    )

    channel_mgr = ChannelManager(scheduler=scheduler)
    feishu_chan = MockFeishuChannel()
    channel_mgr.register_channel(feishu_chan)
    channel_mgr_holder.append(channel_mgr)

    # 模拟外部入站消息
    inbound = InboundMessage(
        channel_type=ChannelType.FEISHU,
        chat_id="chat_001",
        sender_id="user_001",
        text="What is 2+2?",
    )

    handle = channel_mgr.dispatch_inbound(inbound)
    outcome = await handle.wait()
    assert outcome.success

    # 等待异步事件回传投递
    await asyncio.sleep(0.05)
    assert len(sent_outbounds) == 1
    assert sent_outbounds[0].channel_type == ChannelType.FEISHU
    assert sent_outbounds[0].chat_id == "chat_001"
    assert "Echo reply to: What is 2+2?" in sent_outbounds[0].text

    await scheduler.shutdown()
