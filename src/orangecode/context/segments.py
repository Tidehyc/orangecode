"""模块化上下文片段构建器 (SegmentBuilder) 契约与标准实现。"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from orangecode.context.budget import TokenBudget
from orangecode.spine.message import Media


@dataclass
class Segment:
    """单个 SegmentBuilder 对 Prompt / 上下文的贡献。"""

    text: str = ""
    history: list[dict[str, Any]] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssemblyContext:
    """传递给每个 SegmentBuilder 的上下文组装只读输入。"""

    workspace: Path
    session_key: str = "default"
    current_message: str = ""
    media: list[str | Media] | None = None
    channel: str | None = None
    chat_id: str | None = None
    session_messages: list[dict[str, Any]] = field(default_factory=list)
    budget: TokenBudget = field(default_factory=TokenBudget)
    prefix: str | None = None


class SegmentBuilder(Protocol):
    """上下文片段构建器统一协议。"""

    name: str
    order: int
    needs_prefix: bool = False

    async def build(self, ctx: AssemblyContext) -> Segment | None:
        """异步构建该片段。返回 None 表示本轮无内容。"""
        ...


class IdentitySegment:
    """系统身份与运行时环境片段 (Order 1)。"""

    name = "identity"
    order = 1
    needs_prefix = False

    def __init__(self, workspace: Path, agent_name: str = "OrangeCode") -> None:
        self.workspace = workspace
        self.agent_name = agent_name

    async def build(self, ctx: AssemblyContext) -> Segment | None:
        lines = [
            f"# {self.agent_name} Runtime Context",
            f"- Workspace Root: `{self.workspace.resolve()}`",
            f"- Operating System: {platform.system()} {platform.release()} ({platform.machine()})",
            f"- Python Executable: {sys.executable} (Python {platform.python_version()})",
        ]
        if ctx.channel:
            lines.append(f"- Active Channel: {ctx.channel} (chat_id: {ctx.chat_id or 'direct'})")

        return Segment(text="\n".join(lines), meta={"builder": self.name})


class BootstrapSegment:
    """加载工作区引导配置与 Instructions (Order 2)。"""

    name = "bootstrap"
    order = 2
    needs_prefix = False

    def __init__(
        self,
        workspace: Path,
        bootstrap_filenames: list[str] | None = None,
    ) -> None:
        self.workspace = workspace
        self.bootstrap_filenames = bootstrap_filenames or [
            "AGENTS.md",
            "INSTRUCTIONS.md",
            ".orangecode/rules.md",
            "SOUL.md",
        ]

    async def build(self, ctx: AssemblyContext) -> Segment | None:
        found_blocks: list[str] = []
        for rel_name in self.bootstrap_filenames:
            target = self.workspace / rel_name
            if target.is_file():
                try:
                    content = target.read_text(encoding="utf-8").strip()
                    if content:
                        found_blocks.append(f"### Workspace Instruction: {rel_name}\n{content}")
                except Exception:
                    pass

        if not found_blocks:
            return None
        return Segment(text="\n\n".join(found_blocks), meta={"loaded_files": len(found_blocks)})


class MemorySegment:
    """长期记忆与用户画像召回片段 (Order 3)。"""

    name = "memory"
    order = 3
    needs_prefix = False

    def __init__(self, memories: list[str] | None = None) -> None:
        self.memories = memories or []

    async def build(self, ctx: AssemblyContext) -> Segment | None:
        if not self.memories:
            return None

        lines = ["### Retrieved Memory & User Profile:"]
        for m in self.memories:
            m_str = m.strip()
            if m_str:
                lines.append(f"- {m_str}")

        return Segment(text="\n".join(lines), meta={"memory_count": len(self.memories)})


class SkillsSegment:
    """已加载技能目录清单片段 (Order 4)。"""

    name = "skills"
    order = 4
    needs_prefix = False

    def __init__(self, active_skills: list[dict[str, str]] | None = None) -> None:
        self.active_skills = active_skills or []

    async def build(self, ctx: AssemblyContext) -> Segment | None:
        if not self.active_skills:
            return None

        lines = ["### Active Skills & Capabilities:"]
        for skill in self.active_skills:
            name = skill.get("name", "unknown")
            desc = skill.get("description", "")
            lines.append(f"- **{name}**: {desc}")

        return Segment(text="\n".join(lines), meta={"skill_count": len(self.active_skills)})


def render_segments(segments: list[Segment]) -> str:
    """按 order 渲染合并多个 Segment 的文本内容。"""
    texts = [seg.text.strip() for seg in segments if seg and seg.text.strip()]
    return "\n\n".join(texts)
