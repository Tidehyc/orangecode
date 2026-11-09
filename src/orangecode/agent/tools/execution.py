"""工具执行上下文、元能力声明与调用记录数据类。"""

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from orangecode.agent.tools.base import ToolResult


class ToolEffect(StrEnum):
    """工具对外部环境的副作用分类。"""

    UNKNOWN = "unknown"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    EXTERNAL = "external"


@dataclass(frozen=True)
class ToolCapability:
    """声明工具的效果分类与并发执行安全性。"""

    effect: ToolEffect = ToolEffect.UNKNOWN
    concurrency_safe: bool = False


@dataclass(frozen=True)
class ToolExecutionContext:
    """单次工具调用的链路追踪上下文。"""

    call_id: str | None = None
    session_key: str = ""
    iteration: int | None = None
    origin: str | None = None
    parent_call_id: str | None = None

    def child(self, call_id: str | None) -> "ToolExecutionContext":
        return replace(self, call_id=call_id, parent_call_id=self.call_id)


@dataclass(frozen=True)
class ToolInvocation:
    """工具调用的请求载荷封装。"""

    name: str
    arguments: dict[str, Any]
    context: ToolExecutionContext = field(default_factory=ToolExecutionContext)


@dataclass(frozen=True)
class ToolExecution:
    """工具执行完成的完整证据记录。"""

    invocation: ToolInvocation
    result: ToolResult
    duration_ms: float
