import asyncio
import json

import pytest

from orangecode.tui_rpc.brokers import ConfirmBroker, QuestionBroker
from orangecode.tui_rpc.server import TuiRpcServer


@pytest.mark.asyncio
async def test_confirm_broker_success():
    sent_frames = []

    async def mock_send(frame):
        sent_frames.append(frame)

    broker = ConfirmBroker(send_frame=mock_send)

    async def answer_later():
        await asyncio.sleep(0.05)
        assert len(sent_frames) == 1
        req_id = sent_frames[0]["params"]["request_id"]
        ok = broker.resolve(req_id, True)
        assert ok is True

    task = asyncio.create_task(answer_later())
    res = await broker.await_confirm("Delete production DB?", default=False, timeout_seconds=1.0)
    await task
    assert res is True
    assert broker.resolve("non_existent_id", True) is False


@pytest.mark.asyncio
async def test_confirm_broker_timeout():
    broker = ConfirmBroker()
    res = await broker.await_confirm("Do something risky?", default=False, timeout_seconds=0.05)
    assert res is False


@pytest.mark.asyncio
async def test_confirm_broker_cancel_all():
    broker = ConfirmBroker()

    async def cancel_later():
        await asyncio.sleep(0.05)
        broker.cancel_all()

    asyncio.create_task(cancel_later())
    res = await broker.await_confirm("Prompt?", default=True, timeout_seconds=2.0)
    assert res is True


@pytest.mark.asyncio
async def test_question_broker_reply_and_overlap():
    sent_frames = []

    async def mock_send(frame):
        sent_frames.append(frame)

    broker = QuestionBroker(send_frame=mock_send)

    async def answer_later():
        await asyncio.sleep(0.05)
        assert len(sent_frames) >= 1
        cid = sent_frames[0]["params"]["conversation_id"]
        assert broker.pending_req(cid) is not None
        ok = broker.reply(cid, "Python 3.12")
        assert ok is True

    task = asyncio.create_task(answer_later())
    ans = await broker.await_question(
        conversation_id="conv_100",
        prompt="Which python version?",
        choices=["3.11", "3.12"],
        default="3.11",
        timeout_seconds=1.0,
    )
    await task
    assert ans == "Python 3.12"


@pytest.mark.asyncio
async def test_tui_rpc_server_brokers_integration():
    server = TuiRpcServer()

    # Trigger a pending confirm via broker
    confirm_task = asyncio.create_task(
        server.confirm_broker.await_confirm("Proceed with migration?", default=False, timeout_seconds=1.0)
    )
    await asyncio.sleep(0.05)
    pending_ids = list(server.confirm_broker._pending.keys())
    assert len(pending_ids) == 1
    req_id = pending_ids[0]

    # Respond via RPC JSON line
    rpc_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "confirm.respond",
        "params": {"request_id": req_id, "answer": True},
    }
    resp_line = await server.handle_json_line(json.dumps(rpc_req))
    resp_obj = json.loads(resp_line)
    assert resp_obj["result"]["accepted"] is True

    confirmed = await confirm_task
    assert confirmed is True
    server.close()
