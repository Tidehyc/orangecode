"""Context Assembler: 上下文装配与分层预算调度器。"""

from typing import Any

from loguru import logger

from orangecode.context.budget import TokenBudget
from orangecode.context.trimmer import HistoryTrimmer, TrimOutcome


class ContextAssembler:
    """多阶段上下文装配器。"""

    def __init__(self, budget: TokenBudget | None = None) -> None:
        self.budget = budget or TokenBudget()
        self.trimmer = HistoryTrimmer(budget=self.budget)

    def assemble(
        self,
        system_prompt: str | None,
        history: list[dict[str, Any]],
        current_prompt: str,
        memories: list[str] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], TrimOutcome]:
        """将系统身份、召回记忆、历史会话与当前用户提问装配为符合预算的模型输入。"""
        # 1. 组装 System 消息（包含核心 System Prompt 与相关记忆召回段）
        system_parts: list[str] = []
        if system_prompt:
            system_parts.append(system_prompt.strip())

        if memories:
            memory_section = "### Context Memory / Retrieved Knowledge:\n" + "\n".join(
                f"- {m.strip()}" for m in memories if m.strip()
            )
            system_parts.append(memory_section)

        full_system_text = "\n\n".join(system_parts)

        # 2. 组装初始全量消息流
        raw_messages: list[dict[str, Any]] = []
        if full_system_text:
            raw_messages.append({"role": "system", "content": full_system_text})

        if history:
            raw_messages.extend(history)

        raw_messages.append({"role": "user", "content": current_prompt})

        # 3. 运行 HistoryTrimmer 执行原子闭包、工具折叠与预算裁剪
        trim_outcome = self.trimmer.trim(
            messages=raw_messages,
            tools=tools,
            protected_user_count=1,  # 至少完整保护当前这轮提问
        )

        # 4. 验证结构合法性
        errors = self.trimmer.structural_errors(trim_outcome.messages)
        if errors:
            logger.error(f"ContextAssembler found structural errors after trimming: {errors}")

        return trim_outcome.messages, trim_outcome
