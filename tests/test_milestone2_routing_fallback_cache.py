"""测试 Milestone 2：错误分类、跨模型 Fallback 容灾链、KNN 语义模型路由、定价账本与缓存优化。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from orangecode.call_efficiency.ledger import CostLedger
from orangecode.call_efficiency.pricing import calculate_call_cost
from orangecode.providers.base import LLMProvider, LLMResponse, StreamChunk
from orangecode.providers.error_classifier import classify_error
from orangecode.providers.fallback import FallbackProvider
from orangecode.routing.knn_router import ExemplarTask, KNNModelRouter, _text_to_pseudo_embedding
from orangecode.token_wise.system_and_tail_cache import CacheOptimizer


class FailingMockProvider(LLMProvider):
    """模拟失败或超时的 Mock Provider。"""

    def __init__(self, name: str, fail_count: int = 1, error_msg: str = "Rate limit 429") -> None:
        super().__init__(name)
        self.fail_count = fail_count
        self.error_msg = error_msg
        self.attempts = 0

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise RuntimeError(self.error_msg)
        return LLMResponse(content=f"Success from {self.model_name}")

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta_content="test")


def test_error_classification():
    err_429 = RuntimeError("Error code: 429 - rate_limit_exceeded")
    c_429 = classify_error(err_429)
    assert c_429.category == "rate_limit"
    assert c_429.retryable
    assert c_429.should_fallback

    err_ctx = RuntimeError("context_length_exceeded: maximum context length is 8192")
    c_ctx = classify_error(err_ctx)
    assert c_ctx.category == "context_length_exceeded"
    assert c_ctx.should_compress
    assert not c_ctx.retryable


@pytest.mark.asyncio
async def test_fallback_provider_switch_on_failure():
    # 主模型连续失败 3 次，备用模型一次成功
    primary = FailingMockProvider("primary-model", fail_count=5, error_msg="Server 500 error")
    backup = FailingMockProvider("backup-model", fail_count=0)

    provider = FallbackProvider(
        providers=[primary, backup],
        max_retries_per_model=1,
        initial_backoff_seconds=0.01,
    )

    resp = await provider.chat_complete(messages=[{"role": "user", "content": "hi"}])
    assert resp.content == "Success from backup-model"
    assert primary.attempts == 2  # 尝试 1 次 + 重试 1 次
    assert backup.attempts == 1


def test_knn_model_router():
    router = KNNModelRouter(default_model="gpt-4o-mini", k=1)

    # 训练/范例样本 1：复杂推理数学题 -> deepseek-reasoner 收益极高
    math_text = "Prove that there are infinitely many prime numbers using topology."
    math_vec = _text_to_pseudo_embedding(math_text)
    router.add_exemplar(
        ExemplarTask(
            task_name="topology_primes",
            text=math_text,
            embedding=math_vec,
            rewards={"deepseek/deepseek-reasoner": 0.98, "gpt-4o-mini": 0.30},
            costs={"deepseek/deepseek-reasoner": 0.05, "gpt-4o-mini": 0.001},
        )
    )

    # 训练/范例样本 2：极简打招呼问候 -> gpt-4o-mini 收益最高且便宜
    greet_text = "Hello, good morning!"
    greet_vec = _text_to_pseudo_embedding(greet_text)
    router.add_exemplar(
        ExemplarTask(
            task_name="greeting",
            text=greet_text,
            embedding=greet_vec,
            rewards={"deepseek/deepseek-reasoner": 0.60, "gpt-4o-mini": 0.95},
            costs={"deepseek/deepseek-reasoner": 0.05, "gpt-4o-mini": 0.001},
        )
    )

    # 针对类似拓扑数学题的查询进行路由
    selected_model, _ = router.select_model("Prove mathematical theorems about primes")
    assert selected_model == "deepseek/deepseek-reasoner"


def test_pricing_and_cost_ledger():
    ledger = CostLedger()

    # 记录调用：输入 100,000 Token，其中 80,000 命中缓存；输出 2,000 Token
    receipt = ledger.record(
        model="deepseek/deepseek-chat",
        prompt_tokens=100_000,
        completion_tokens=2_000,
        cache_read_tokens=80_000,
    )

    assert receipt.cost_usd > 0
    assert ledger.total_tokens == 102_000
    assert ledger.total_cache_read_tokens == 80_000

    # 验证普通计费对比缓存命中的优惠节省
    cost_no_cache = calculate_call_cost("deepseek/deepseek-chat", prompt_tokens=100_000, completion_tokens=2_000, cache_read_tokens=0)
    assert receipt.cost_usd < cost_no_cache


def test_cache_optimizer_tools_canonical():
    tools = [
        {"type": "function", "function": {"name": "write_file"}},
        {"type": "function", "function": {"name": "ask_user"}},
        {"type": "function", "function": {"name": "edit_file"}},
    ]
    sorted_tools = CacheOptimizer.canonicalize_tools_schema(tools)
    names = [t["function"]["name"] for t in sorted_tools]
    assert names == ["ask_user", "edit_file", "write_file"]
