"""Context Assembler: 上下文装配与分层预算调度器。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from orangecode.context.budget import TokenBudget
from orangecode.context.segments import (
    AssemblyContext,
    Segment,
    SegmentBuilder,
    render_segments,
)
from orangecode.context.trimmer import HistoryTrimmer, TrimOutcome
from orangecode.spine.message import Media, build_user_content


class ContextAssembler:
    """多阶段上下文装配器，支持模块化 Segment 构建器与多模态媒体输入。"""

    def __init__(
        self,
        budget: TokenBudget | None = None,
        segment_builders: list[SegmentBuilder] | None = None,
    ) -> None:
        self.budget = budget or TokenBudget()
        self.trimmer = HistoryTrimmer(budget=self.budget)
        self.segment_builders: list[SegmentBuilder] = sorted(
            segment_builders or [],
            key=lambda b: getattr(b, "order", 99),
        )

    async def assemble_async(
        self,
        workspace: Path | None = None,
        system_prompt: str | None = None,
        history: list[dict[str, Any]] | None = None,
        current_prompt: str = "",
        media: list[str | Media] | None = None,
        memories: list[str] | None = None,
        tools: list[dict[str, Any]] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], TrimOutcome]:
        """异步执行各 Segment 构建阶段，装配并裁剪完整上下文。"""
        ws = workspace or Path.cwd()
        ctx = AssemblyContext(
            workspace=ws,
            current_message=current_prompt,
            media=media,
            channel=channel,
            chat_id=chat_id,
            session_messages=list(history or []),
            budget=self.budget,
        )

        # 阶段 A：执行所有独立的 SegmentBuilder
        segments: list[Segment] = []
        for builder in self.segment_builders:
            try:
                seg = await builder.build(ctx)
                if seg:
                    segments.append(seg)
            except Exception as e:
                logger.warning(f"Error in SegmentBuilder '{getattr(builder, 'name', 'unknown')}': {e}")

        # 拼接动态 segment 文本
        built_system_text = render_segments(segments)

        # 合并传入的显式 system_prompt 与 memories
        system_parts: list[str] = []
        if system_prompt and system_prompt.strip():
            system_parts.append(system_prompt.strip())
        if built_system_text:
            system_parts.append(built_system_text)
        if memories:
            memory_section = "### Context Memory / Retrieved Knowledge:\n" + "\n".join(
                f"- {m.strip()}" for m in memories if m.strip()
            )
            system_parts.append(memory_section)

        full_system_text = "\n\n".join(system_parts)

        # 组装初始全量消息流
        raw_messages: list[dict[str, Any]] = []
        if full_system_text:
            raw_messages.append({"role": "system", "content": full_system_text})

        if history:
            raw_messages.extend(history)

        user_content = build_user_content(current_prompt, media=media)
        raw_messages.append({"role": "user", "content": user_content})

        # 运行 HistoryTrimmer 执行原子闭包、工具折叠与预算裁剪
        trim_outcome = self.trimmer.trim(
            messages=raw_messages,
            tools=tools,
            protected_user_count=1,
        )

        # 验证结构合法性
        errors = self.trimmer.structural_errors(trim_outcome.messages)
        if errors:
            logger.error(f"ContextAssembler found structural errors after trimming: {errors}")

        return trim_outcome.messages, trim_outcome

    def assemble(
        self,
        system_prompt: str | None,
        history: list[dict[str, Any]],
        current_prompt: str,
        memories: list[str] | None = None,
        tools: list[dict[str, Any]] | None = None,
        media: list[str | Media] | None = None,
        workspace: Path | None = None,
    ) -> tuple[list[dict[str, Any]], TrimOutcome]:
        """同步包装方法，保持向后兼容性。"""
        # 如果存在需要异步执行的 segment_builders，使用 asyncio.run 或直接就地快速组装
        if self.segment_builders:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # 如果在已有 loop 内部被同步调用，退化为无动态 builder 的安全纯文本装配
                return self._assemble_sync_core(
                    system_prompt=system_prompt,
                    history=history,
                    current_prompt=current_prompt,
                    memories=memories,
                    tools=tools,
                    media=media,
                )
            else:
                return asyncio.run(
                    self.assemble_async(
                        workspace=workspace,
                        system_prompt=system_prompt,
                        history=history,
                        current_prompt=current_prompt,
                        media=media,
                        memories=memories,
                        tools=tools,
                    )
                )

        return self._assemble_sync_core(
            system_prompt=system_prompt,
            history=history,
            current_prompt=current_prompt,
            memories=memories,
            tools=tools,
            media=media,
        )

    def _assemble_sync_core(
        self,
        system_prompt: str | None,
        history: list[dict[str, Any]],
        current_prompt: str,
        memories: list[str] | None = None,
        tools: list[dict[str, Any]] | None = None,
        media: list[str | Media] | None = None,
    ) -> tuple[list[dict[str, Any]], TrimOutcome]:
        system_parts: list[str] = []
        if system_prompt and system_prompt.strip():
            system_parts.append(system_prompt.strip())

        if memories:
            memory_section = "### Context Memory / Retrieved Knowledge:\n" + "\n".join(
                f"- {m.strip()}" for m in memories if m.strip()
            )
            system_parts.append(memory_section)

        full_system_text = "\n\n".join(system_parts)

        raw_messages: list[dict[str, Any]] = []
        if full_system_text:
            raw_messages.append({"role": "system", "content": full_system_text})

        if history:
            raw_messages.extend(history)

        user_content = build_user_content(current_prompt, media=media)
        raw_messages.append({"role": "user", "content": user_content})

        trim_outcome = self.trimmer.trim(
            messages=raw_messages,
            tools=tools,
            protected_user_count=1,
        )

        errors = self.trimmer.structural_errors(trim_outcome.messages)
        if errors:
            logger.error(f"ContextAssembler found structural errors after trimming: {errors}")

        return trim_outcome.messages, trim_outcome
