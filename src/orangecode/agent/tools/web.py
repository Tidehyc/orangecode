"""网页检索与内容抓取工具：WebFetch 与 WebSearch。"""

import re
from typing import Any

import httpx

from orangecode.agent.tools.base import Tool, ToolResult
from orangecode.agent.tools.execution import ToolCapability, ToolEffect
from orangecode.security.network import validate_url_target
from orangecode.security.trust import wrap_untrusted


class WebFetchTool(Tool):
    """抓取指定 URL 网页内容，并自动清洗提取可读文本。"""

    name = "web_fetch"
    description = (
        "Fetch content from a web URL and extract readable, clean text/markdown. "
        "Strips HTML tags, stylesheets, and scripts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full HTTP/HTTPS URL to fetch.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters of text to return. Defaults to 8000.",
            },
        },
        "required": ["url"],
    }
    capability = ToolCapability(effect=ToolEffect.EXTERNAL, concurrency_safe=True)
    timeout_seconds = 30.0

    @staticmethod
    def _clean_html(html: str) -> str:
        # 去除 script 与 style 块
        clean = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # 去除所有 html 标签
        clean = re.sub(r"<[^>]+>", " ", clean)
        # 压缩连续空白
        clean = re.sub(r"[ \t]+", " ", clean)
        clean = re.sub(r"\n\s*\n+", "\n\n", clean)
        return clean.strip()

    async def execute(self, url: str, max_chars: int = 8000, **kwargs: Any) -> ToolResult:
        is_safe, error_msg = validate_url_target(url)
        if not is_safe:
            return ToolResult(f"Security error: Blocked unsafe URL '{url}': {error_msg}", failed=True)

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; OrangeCodeAgent/0.1; +https://github.com/orangecode)"
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")

                if "application/json" in content_type:
                    text = resp.text
                else:
                    text = self._clean_html(resp.text)

                if len(text) > max_chars:
                    text = text[:max_chars] + f"\n\n[... Truncated at {max_chars} characters ...]"

                fenced_text = wrap_untrusted(text, source=f"web:{url}")
                return ToolResult(f"Content from {url}:\n\n{fenced_text}", failed=False)
        except httpx.HTTPStatusError as e:
            return ToolResult(f"HTTP error {e.response.status_code} fetching '{url}'.", failed=True)
        except Exception as e:
            return ToolResult(f"Failed to fetch '{url}': {e}", failed=True)


class WebSearchTool(Tool):
    """执行在线关键字搜索，返回相关网页标题、链接与摘要片段。"""

    name = "web_search"
    description = "Search the web for keywords to gather current external information."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query terms.",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return. Defaults to 5.",
            },
        },
        "required": ["query"],
    }
    capability = ToolCapability(effect=ToolEffect.EXTERNAL, concurrency_safe=True)
    timeout_seconds = 20.0

    async def execute(self, query: str, num_results: int = 5, **kwargs: Any) -> ToolResult:
        # 使用轻量且无鉴权的搜索端点或标准聚合，优雅降级
        search_url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(search_url, data={"q": query}, headers=headers)
                if resp.status_code == 200:
                    # 简单匹配结果链接与摘要
                    snippets = re.findall(
                        r'<a class="result__snippet[^>]*>(.*?)</a>',
                        resp.text,
                        flags=re.DOTALL,
                    )
                    re.findall(
                        r'<a class="result__url[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                        resp.text,
                        flags=re.DOTALL,
                    )
                    items: list[str] = []
                    for idx, snip in enumerate(snippets[:num_results], start=1):
                        clean_snip = re.sub(r"<[^>]+>", "", snip).strip()
                        items.append(f"{idx}. {clean_snip}")

                    if items:
                        return ToolResult(f"Search results for '{query}':\n\n" + "\n".join(items), failed=False)

            return ToolResult(f"Search for '{query}' completed with no direct snippets parsed.", failed=False)
        except Exception as e:
            return ToolResult(f"Search query '{query}' encountered error: {e}", failed=True)
