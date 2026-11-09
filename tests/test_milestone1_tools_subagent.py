"""测试 Milestone 1：全套扩展工具集（Edit, ListDir, Find, Grep, Web, AskUser, ToolIndex）与 Subagent 并发派发。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from orangecode.agent.subagent.manager import SpawnTool, SubagentManager
from orangecode.agent.tools.ask_user import AskUserTool
from orangecode.agent.tools.file_search import FindTool, GrepTool
from orangecode.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from orangecode.agent.tools.tool_index import ToolIndex
from orangecode.agent.tools.tool_search import ToolSearchTool
from orangecode.agent.tools.web import WebFetchTool
from orangecode.providers.base import (
    LLMProvider,
    LLMResponse,
    StreamChunk,
    TokenUsage,
    ToolCallRequest,
)


class MockSubagentProvider(LLMProvider):
    """支持子智能体测试的多回复 Provider。"""

    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__("mock-subagent")
        self.responses = responses

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="Subagent fallback answer")

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta_content="subagent chunk")


@pytest.mark.asyncio
async def test_edit_file_tool(tmp_path):
    target_file = tmp_path / "code.py"
    target_file.write_text("def hello():\n    return 'old'\n", encoding="utf-8")

    editor = EditFileTool()

    # 1. 精确替换
    res = await editor.execute(
        path=str(target_file),
        target="return 'old'",
        replacement="return 'new'",
    )
    assert not res.failed
    assert "return 'new'" in target_file.read_text(encoding="utf-8")

    # 2. 目标不存在
    res_fail = await editor.execute(
        path=str(target_file),
        target="non_existent_code",
        replacement="foo",
    )
    assert res_fail.failed


@pytest.mark.asyncio
async def test_list_dir_tool(tmp_path):
    (tmp_path / "dir_a").mkdir()
    (tmp_path / "file_b.txt").write_text("content", encoding="utf-8")

    lister = ListDirTool()
    res = await lister.execute(path=str(tmp_path))
    assert not res.failed
    assert "[DIR]  dir_a" in res
    assert "[FILE] file_b.txt" in res


@pytest.mark.asyncio
async def test_find_and_grep_tools(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    f1 = src_dir / "service.py"
    f2 = src_dir / "util.py"
    f1.write_text("class DatabaseService:\n    pass\n", encoding="utf-8")
    f2.write_text("def connect_database():\n    return True\n", encoding="utf-8")

    # FindTool
    finder = FindTool()
    find_res = await finder.execute(pattern="*.py", root_path=str(tmp_path))
    assert not find_res.failed
    assert "service.py" in find_res
    assert "util.py" in find_res

    # GrepTool
    grepper = GrepTool()
    grep_res = await grepper.execute(query=r"Database", root_path=str(tmp_path))
    assert not grep_res.failed
    assert "service.py:1: class DatabaseService:" in grep_res


def test_web_fetch_html_cleaning():
    raw_html = (
        "<html><head><style>body {color:red;}</style><script>alert(1);</script></head>"
        "<body><h1>Title</h1><p>Main content article text.</p></body></html>"
    )
    cleaned = WebFetchTool._clean_html(raw_html)
    assert "alert(1)" not in cleaned
    assert "color:red" not in cleaned
    assert "Title" in cleaned
    assert "Main content article text." in cleaned


@pytest.mark.asyncio
async def test_ask_user_tool():
    async def mock_handler(q: str, opts: list[str] | None) -> str:
        return "User confirmed yes"

    tool = AskUserTool(input_handler=mock_handler)
    res = await tool.execute(question="Proceed with delete?", options=["yes", "no"])
    assert not res.failed
    assert res == "User confirmed yes"


@pytest.mark.asyncio
async def test_tool_index_and_search():
    index = ToolIndex([
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        FindTool(),
    ])

    search_tool = ToolSearchTool(index=index)
    res = await search_tool.execute(query="find file glob")
    assert not res.failed
    assert "find_files" in res
    assert "Parameters:" in res


@pytest.mark.asyncio
async def test_subagent_manager_and_spawn(tmp_path):
    # 模拟子智能体执行文件操作并总结返回
    mock_responses = [
        LLMResponse(
            content="I will write the report.",
            tool_calls=[
                ToolCallRequest(
                    id="call_write_sub",
                    name="write_file",
                    arguments={"path": str(tmp_path / "subagent_output.txt"), "content": "Done by subagent"},
                )
            ],
            usage=TokenUsage(total_tokens=25),
        ),
        LLMResponse(
            content="Task completed: subagent_output.txt has been written.",
            usage=TokenUsage(total_tokens=20),
        ),
    ]

    mock_provider = MockSubagentProvider(mock_responses)
    manager = SubagentManager(provider=mock_provider)
    spawn_tool = SpawnTool(manager=manager)

    res = await spawn_tool.execute(
        task="Write subagent_output.txt",
        label="file-writer",
    )
    assert not res.failed
    assert "Task completed" in res
    assert (tmp_path / "subagent_output.txt").exists()
    assert (tmp_path / "subagent_output.txt").read_text() == "Done by subagent"
