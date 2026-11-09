"""工具描述索引库：基于 BM25 关键词相关度实现海量工具的快速检索。"""


from orangecode.agent.tools.base import Tool
from orangecode.utils.bm25 import BM25Okapi


class ToolIndex:
    """海量工具索引中心。"""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._corpus: list[str] = []
        self._tool_names: list[str] = []
        self._bm25: BM25Okapi | None = None

        if tools:
            for t in tools:
                self.add_tool(t)

    def add_tool(self, tool: Tool) -> None:
        """向索引中心注册工具并更新搜索语料。"""
        self._tools[tool.name] = tool
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._tool_names = list(self._tools.keys())
        self._corpus = [
            f"{t.name} {t.description} {' '.join(t.parameters.get('properties', {}).keys())}"
            for t in self._tools.values()
        ]
        self._bm25 = BM25Okapi(self._corpus) if self._corpus else None

    def search(self, query: str, limit: int = 5) -> list[Tool]:
        """根据自然语言意图搜索最契合的工具实例列表。"""
        if not self._bm25 or not self._tool_names:
            return []

        top_matches = self._bm25.search_top_k(query, k=limit)
        results: list[Tool] = []
        for idx, _ in top_matches:
            name = self._tool_names[idx]
            results.append(self._tools[name])
        return results

    def get_tool(self, name: str) -> Tool | None:
        """按工具名称精确获取。"""
        return self._tools.get(name)

    def all_tools(self) -> list[Tool]:
        """返回全部已索引工具。"""
        return list(self._tools.values())
