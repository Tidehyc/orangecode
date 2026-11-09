"""Spine 生命周期事件与输出流事件模型。"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class Usage:
    """Turn 维度的 Token 消耗统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ToolPhase(StrEnum):
    """工具调用的时段标记。"""

    START = "start"
    COMPLETE = "complete"


# ----------------------------------------------------------------------
# 运行时生命周期事件 (由 Worker / Scheduler 发出)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class TurnStarted:
    """Turn 开始执行事件。"""

    conversation_id: str
    turn_id: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class TurnEnded:
    """Turn 正常执行完成事件。"""

    conversation_id: str
    turn_id: str
    final_content: str
    usage: Usage
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class TurnFailed:
    """Turn 发生异常失败事件。"""

    conversation_id: str
    turn_id: str
    error: str
    timestamp: datetime = field(default_factory=datetime.now)


# ----------------------------------------------------------------------
# 内容与进度事件 (由 Agent 执行过程中发出)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class TextDelta:
    """流式文本输出增量。"""

    delta: str


@dataclass(frozen=True)
class ToolEvent:
    """工具调用的执行状态事件。"""

    tool_name: str
    phase: ToolPhase
    arguments: dict[str, Any] | None = None
    result: str | None = None
    failed: bool = False


@dataclass(frozen=True)
class Notice:
    """带外状态或进度提示。"""

    message: str
    kind: str = "info"  # "info", "warning", "injected", "interrupted"


TurnEvent = TurnStarted | TurnEnded | TurnFailed | TextDelta | ToolEvent | Notice
