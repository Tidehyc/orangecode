"""LLM 错误结构化分类器：区分重试、跨模型降级与上下文压缩。"""

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ErrorClassification:
    """LLM 调用失败的结构化判定证据。"""

    category: str
    retryable: bool = False
    should_fallback: bool = False
    should_compress: bool = False
    description: str = ""


def classify_error(err: Exception) -> ErrorClassification:
    """根据异常类型、状态码与错误信息对 LLM 失败进行归类。"""
    err_str = str(err).lower()

    # 1. 上下文超限 (Context Window Overflow) -> 需要 Shrink / Compress
    if any(k in err_str for k in ("context_length_exceeded", "maximum context length", "too many tokens", "prompt is too long")):
        return ErrorClassification(
            category="context_length_exceeded",
            retryable=False,
            should_fallback=False,
            should_compress=True,
            description="Context window overflow, history compression required.",
        )

    # 2. 频率限制 (Rate Limit / Quota Exceeded) -> 可指数退避重试，或降级到备用模型
    if any(k in err_str for k in ("rate_limit", "rate limit", "429", "insufficient_quota")):
        return ErrorClassification(
            category="rate_limit",
            retryable=True,
            should_fallback=True,
            description="Rate limit or quota threshold reached.",
        )

    # 3. 超时 (Timeout) -> 可短时重试，可降级
    if isinstance(err, (httpx.TimeoutException, TimeoutError)) or "timed out" in err_str:
        return ErrorClassification(
            category="timeout",
            retryable=True,
            should_fallback=True,
            description="Network request timed out.",
        )

    # 4. 服务端错误 (500, 502, 503, 504) -> 可重试，或降级到其它 Provider
    if any(k in err_str for k in ("500", "502", "503", "504", "internal server error", "service unavailable")):
        return ErrorClassification(
            category="server_error",
            retryable=True,
            should_fallback=True,
            description="Upstream server error encountered.",
        )

    # 5. 鉴权失败 (401, 403, invalid api key) -> 不可重试，直接抛出或降级
    if any(k in err_str for k in ("401", "403", "unauthorized", "invalid api key", "authentication")):
        return ErrorClassification(
            category="authentication_failed",
            retryable=False,
            should_fallback=True,
            description="Authentication or permission error.",
        )

    # 6. 未知客户端错误
    return ErrorClassification(
        category="unknown",
        retryable=False,
        should_fallback=False,
        description=f"Unclassified client error: {type(err).__name__}",
    )
