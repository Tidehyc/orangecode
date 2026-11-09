"""上下文预算定义与分配策略。"""

from dataclasses import dataclass


@dataclass
class TokenBudget:
    """定义单轮模型调用的 Token 预算空间分配。"""

    # 上下文窗口总量（如 128k 或 32k）
    context_window: int = 32_000

    # 预留给 LLM 生成回复的输出 Token 空间
    reserved_output: int = 4_096

    # 预留给 System Prompt 与核心身份的 Token
    reserved_system: int = 2_048

    # 预留给动态召回记忆（Memory / RAG）的 Token
    reserved_memory: int = 2_048

    @property
    def max_prompt_tokens(self) -> int:
        """输入 Prompt 允许占用的最高 Token 上限。"""
        return max(1, self.context_window - self.reserved_output)

    @property
    def max_history_tokens(self) -> int:
        """预留给历史对话轮次的最大 Token 配额。"""
        remaining = self.max_prompt_tokens - self.reserved_system - self.reserved_memory
        return max(100, remaining)
