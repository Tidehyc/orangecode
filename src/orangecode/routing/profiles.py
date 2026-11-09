"""模型能力画像与参数画像矩阵。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    """大模型能力与成本画像。"""

    name: str
    tier: str  # "fast", "balanced", "powerful"
    context_window: int = 128_000
    cost_per_m_input: float = 1.0     # 每百万输入 Token 美元单价
    cost_per_m_output: float = 3.0    # 每百万输出 Token 美元单价
    reasoning_score: float = 80.0     # 评测推理能力参考分 (0-100)


# 默认内置画像矩阵
DEFAULT_PROFILES: dict[str, ModelProfile] = {
    "deepseek/deepseek-chat": ModelProfile(
        name="deepseek/deepseek-chat",
        tier="balanced",
        cost_per_m_input=0.14,
        cost_per_m_output=0.28,
        reasoning_score=85.0,
    ),
    "deepseek/deepseek-reasoner": ModelProfile(
        name="deepseek/deepseek-reasoner",
        tier="powerful",
        cost_per_m_input=0.55,
        cost_per_m_output=2.19,
        reasoning_score=95.0,
    ),
    "gpt-4o-mini": ModelProfile(
        name="gpt-4o-mini",
        tier="fast",
        cost_per_m_input=0.15,
        cost_per_m_output=0.60,
        reasoning_score=78.0,
    ),
    "gpt-4o": ModelProfile(
        name="gpt-4o",
        tier="powerful",
        cost_per_m_input=2.50,
        cost_per_m_output=10.00,
        reasoning_score=94.0,
    ),
}
