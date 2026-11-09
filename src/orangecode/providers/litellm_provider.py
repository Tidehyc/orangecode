"""基于 LiteLLM 的多模型统一 Provider 实现。"""

import json
from collections.abc import AsyncIterator
from typing import Any

import litellm
from loguru import logger

from orangecode.providers.base import (
    LLMProvider,
    LLMResponse,
    StreamChunk,
    TokenUsage,
    ToolCallRequest,
)


class LiteLLMProvider(LLMProvider):
    """通用 LiteLLM 接入层，支持 100+ 大模型。"""

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model_name, **kwargs)
        self.api_key = api_key
        self.api_base = api_base
        # 关闭 litellm 冗余遥测和过度日志
        litellm.telemetry = False

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 litellm.acompletion。"""
        call_params: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            **self.extra_kwargs,
            **kwargs,
        }
        if self.api_key:
            call_params["api_key"] = self.api_key
        if self.api_base:
            call_params["api_base"] = self.api_base
        if max_tokens:
            call_params["max_tokens"] = max_tokens
        if tools:
            call_params["tools"] = tools
            call_params["tool_choice"] = "auto"

        logger.debug(f"Calling LLM {self.model_name} with {len(messages)} messages")
        response = await litellm.acompletion(**call_params)

        choice = response.choices[0]
        message = choice.message
        content = message.content or None

        parsed_tool_calls: list[ToolCallRequest] = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                fn_name = tc.function.name
                raw_args = tc.function.arguments
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {"raw_arguments": raw_args}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}
                parsed_tool_calls.append(
                    ToolCallRequest(
                        id=tc.id or f"call_{fn_name}",
                        name=fn_name,
                        arguments=args,
                    )
                )

        usage = TokenUsage()
        if hasattr(response, "usage") and response.usage:
            usage.prompt_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
            usage.completion_tokens = getattr(response.usage, "completion_tokens", 0) or 0
            usage.total_tokens = getattr(response.usage, "total_tokens", 0) or 0

        return LLMResponse(
            content=content,
            tool_calls=parsed_tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason,
            raw_response=response,
        )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用 litellm.acompletion。"""
        call_params: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            **self.extra_kwargs,
            **kwargs,
        }
        if self.api_key:
            call_params["api_key"] = self.api_key
        if self.api_base:
            call_params["api_base"] = self.api_base
        if max_tokens:
            call_params["max_tokens"] = max_tokens
        if tools:
            call_params["tools"] = tools

        response_stream = await litellm.acompletion(**call_params)
        async for chunk in response_stream:
            choice = chunk.choices[0]
            delta = choice.delta
            delta_content = getattr(delta, "content", None)
            yield StreamChunk(
                delta_content=delta_content,
                finish_reason=choice.finish_reason,
            )
