import pytest

from orangecode.eval_engine.engine import EvalEngine
from orangecode.eval_engine.hooks import ToolAuditHook
from orangecode.eval_engine.judge import EvalJudge
from orangecode.providers.base import LLMProvider, LLMResponse


class MockJudgeProvider(LLMProvider):
    def __init__(self, answer_json: str):
        super().__init__("mock-judge")
        self.answer_json = answer_json

    async def chat_complete(self, messages, **kwargs):
        return LLMResponse(content=self.answer_json)

    async def stream_chat(self, messages, **kwargs):
        yield None


@pytest.mark.asyncio
async def test_tool_audit_hook():
    hook = ToolAuditHook()
    await hook.on_tool_call("bash", {"cmd": "ls"}, "file1.txt", failed=False)
    await hook.on_tool_call("bash", {"cmd": "cat bad"}, "not found", failed=True)

    summary = hook.summary()
    assert summary["total_calls"] == 2
    assert summary["failed_calls"] == 1
    assert summary["success_rate"] == 0.5
    assert "bash" in summary["tools_used"]


@pytest.mark.asyncio
async def test_eval_judge_and_engine():
    provider = MockJudgeProvider('{"score": 0.95, "passed": true, "reasoning": "Accurate response"}')
    judge = EvalJudge(provider=provider)

    verdict = await judge.judge(query="What is 1+1?", response="1+1=2")
    assert verdict.score == 0.95
    assert verdict.passed is True
    assert "Accurate" in verdict.reasoning

    engine = EvalEngine(provider=provider)
    await engine.audit_hook.on_tool_call("read_file", {"path": "a.txt"}, "ok", failed=False)

    report = await engine.evaluate_task(query="Check a.txt", response="Content is ok")
    assert report["passed"] is True
    assert report["tool_audit"]["total_calls"] == 1
