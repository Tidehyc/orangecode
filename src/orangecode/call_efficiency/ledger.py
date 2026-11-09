"""调用账本：记录会话与全局的模型财务开销与缓存节省。"""

from dataclasses import dataclass, field
from datetime import datetime

from orangecode.call_efficiency.pricing import calculate_call_cost


@dataclass(frozen=True)
class CallReceipt:
    """单次模型调用的开销账单收据。"""

    model: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cost_usd: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class CostLedger:
    """财务账本跟踪器。"""

    def __init__(self) -> None:
        self.receipts: list[CallReceipt] = []

    def record(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> CallReceipt:
        """记录一次调用并返回结算收据。"""
        cost = calculate_call_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )
        receipt = CallReceipt(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cost_usd=cost,
        )
        self.receipts.append(receipt)
        return receipt

    @property
    def total_cost_usd(self) -> float:
        """累计总支出（美元）。"""
        return sum(r.cost_usd for r in self.receipts)

    @property
    def total_tokens(self) -> int:
        """累计总 Token 消耗。"""
        return sum(r.prompt_tokens + r.completion_tokens for r in self.receipts)

    @property
    def total_cache_read_tokens(self) -> int:
        """累计命中的缓存 Token 数。"""
        return sum(r.cache_read_tokens for r in self.receipts)
