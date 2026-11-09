"""多模型容灾重试与自动 Fallback 降级链。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from orangecode.providers.base import LLMProvider, LLMResponse, StreamChunk
from orangecode.providers.error_classifier import classify_error


class FallbackProvider(LLMProvider):
    """支持同模型指数退避重试与跨模型自动降级的复合 Provider。"""

    def __init__(
        self,
        providers: list[LLMProvider],
        max_retries_per_model: int = 2,
        initial_backoff_seconds: float = 0.5,
    ) -> None:
        if not providers:
            raise ValueError("FallbackProvider requires at least one provider.")
        super().__init__(model_name=providers[0].model_name)
        self.providers = providers
        self.max_retries_per_model = max_retries_per_model
        self.initial_backoff_seconds = initial_backoff_seconds

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        last_exception: Exception | None = None

        for idx, provider in enumerate(self.providers):
            backoff = self.initial_backoff_seconds
            for attempt in range(self.max_retries_per_model + 1):
                try:
                    logger.debug(
                        f"Attempting model [{provider.model_name}] (tier {idx + 1}/{len(self.providers)}, "
                        f"attempt {attempt + 1})"
                    )
                    return await provider.chat_complete(
                        messages=messages,
                        tools=tools,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs,
                    )
                except Exception as err:
                    last_exception = err
                    classification = classify_error(err)
                    logger.warning(
                        f"Model [{provider.model_name}] attempt {attempt + 1} failed: "
                        f"category={classification.category}, desc={classification.description}"
                    )

                    # 如果错误指示上下文超限，不可重试，直接抛给上层做压缩
                    if classification.should_compress:
                        raise

                    # 如果不可重试或重试次数用尽，则跳出该模型尝试下一个 Fallback
                    if not classification.retryable or attempt >= self.max_retries_per_model:
                        break

                    # 指数退避等待重试
                    logger.info(f"Retrying [{provider.model_name}] in {backoff:.2f}s...")
                    await asyncio.sleep(backoff)
                    backoff *= 2.0

            # 当前模型全部尝试失败，如果还有备用模型，则触发跨模型 Fallback
            if idx + 1 < len(self.providers):
                next_provider = self.providers[idx + 1]
                logger.warning(
                    f"Initiating cross-model fallback from [{provider.model_name}] -> [{next_provider.model_name}]"
                )

        # 全部 Provider 均耗尽失败
        assert last_exception is not None
        raise last_exception

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        # 流式调用默认使用主 Provider，失败时抛出异常
        primary = self.providers[0]
        async for chunk in primary.stream_chat(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            yield chunk
