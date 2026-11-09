"""Prompt 缓存对齐与尾部滑动窗口优化器。"""

from typing import Any


class CacheOptimizer:
    """提示词缓存对齐器：确保前缀静态对齐，最大化大模型 KV Cache 命中率。"""

    @staticmethod
    def canonicalize_tools_schema(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """对工具定义按名称字母序稳定排序，确保跨轮次调用的工具签名字符 100% 一致。"""
        if not tools:
            return None
        # 深拷贝并按 function.name 排序
        return sorted(
            tools,
            key=lambda t: t.get("function", {}).get("name", ""),
        )

    @staticmethod
    def align_system_prefix(
        system_prompt: str,
        static_context: str | None = None,
    ) -> str:
        """格式化并标准化系统前缀文本，消除随机空格与换行漂移。"""
        parts = [system_prompt.strip()]
        if static_context:
            parts.append(static_context.strip())
        return "\n\n".join(parts)
