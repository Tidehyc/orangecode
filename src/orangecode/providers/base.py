"""LLM Provider 基础契约、请求与响应模型定义。"""

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRequest:
    """承载 LLM 生成的规范化 Tool Call 请求。"""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_openai_tool_call(self) -> dict[str, Any]:
        """转换为 OpenAI 标准的 tool_call 格式。"""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class TokenUsage:
    """Token 消耗统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM 调用的规范化统一响应对象。"""

    content: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str | None = None
    raw_response: Any = None

    @property
    def has_tool_calls(self) -> bool:
        """是否存在工具调用请求。"""
        return len(self.tool_calls) > 0


@dataclass
class StreamChunk:
    """流式返回的分片。"""

    delta_content: str | None = None
    delta_tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str | None = None


class LLMProvider(ABC):
    """所有大模型供应商的抽象基类。"""

    def __init__(self, model_name: str, **kwargs: Any) -> None:
        self.model_name = model_name
        self.extra_kwargs = kwargs

    @abstractmethod
    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """执行单次对话补全。"""
        raise NotImplementedError

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """执行流式对话补全。"""
        raise NotImplementedError
