"""精确到 Token 维度的调用成本测算中心。"""


# 单价表（单位：美元/Token）
_BASE_RATES: dict[str, tuple[float, float]] = {
    # model_name: (input_rate, output_rate)
    "deepseek/deepseek-chat": (0.14e-6, 0.28e-6),
    "deepseek/deepseek-reasoner": (0.55e-6, 2.19e-6),
    "gpt-4o-mini": (0.15e-6, 0.60e-6),
    "gpt-4o": (2.50e-6, 10.00e-6),
    "claude-3-5-sonnet": (3.00e-6, 15.00e-6),
}


def calculate_call_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """计算单次大模型调用的真实财务成本（美元）。

    对于支持 Prompt Caching 的模型（如 DeepSeek / Anthropic），
    缓存命中的输入 Token 享受 10%~20% 的极低费率。
    """
    input_rate, output_rate = _BASE_RATES.get(model, (1.0e-6, 3.0e-6))

    # 普通未命中缓存输入
    regular_input_tokens = max(0, prompt_tokens - cache_read_tokens)
    cost = regular_input_tokens * input_rate

    # 缓存读取费率（通常为基准输入费率的 10%）
    cost += cache_read_tokens * (input_rate * 0.1)

    # 缓存写入费率（通常为基准输入费率的 125%）
    cost += cache_write_tokens * (input_rate * 1.25)

    # 补全生成输出费率
    cost += completion_tokens * output_rate

    return round(cost, 8)
