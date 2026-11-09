"""文件搜索与内容匹配工具：Find (路径通配符搜索) 与 Grep (文件内容正则搜索)。"""

import re
from pathlib import Path
from typing import Any

from orangecode.agent.tools.base import Tool, ToolResult
from orangecode.agent.tools.execution import ToolCapability, ToolEffect


class FindTool(Tool):
    """基于 Glob 通配符模式在目录树中搜索匹配的文件或目录。"""

    name = "find_files"
    description = (
        "Find files matching a glob pattern (e.g., '**/*.py', 'src/**/*.json') "
        "recursively in a directory."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The glob pattern to match against (e.g. '**/*.py').",
            },
            "root_path": {
                "type": "string",
                "description": "The base directory to start searching from. Defaults to '.'.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of file paths to return. Defaults to 100.",
            },
        },
        "required": ["pattern"],
    }
    capability = ToolCapability(effect=ToolEffect.READ, concurrency_safe=True)

    async def execute(
        self,
        pattern: str,
        root_path: str = ".",
        max_results: int = 100,
        **kwargs: Any,
    ) -> ToolResult:
        base = Path(root_path).resolve()
        if not base.exists() or not base.is_dir():
            return ToolResult(f"Error: Invalid root_path '{root_path}'.", failed=True)

        try:
            # 若 pattern 不含路径分隔符，则自动扩充为 **/{pattern} 形成任意深度搜索
            glob_pat = pattern if "/" in pattern or pattern.startswith("**") else f"**/{pattern}"
            matches: list[str] = []
            for p in base.glob(glob_pat):
                # 排除 .git 与 .venv 等虚拟环境路径
                parts = p.parts
                if ".git" in parts or ".venv" in parts or "__pycache__" in parts:
                    continue
                rel_path = p.relative_to(base)
                suffix = "/" if p.is_dir() else ""
                matches.append(f"{rel_path}{suffix}")
                if len(matches) >= max_results:
                    break

            if not matches:
                return ToolResult(
                    f"No files matched pattern '{pattern}' under '{root_path}'.",
                    failed=False,
                )

            header = f"Found {len(matches)} match(es) for pattern '{pattern}' in '{root_path}':\n"
            return ToolResult(header + "\n".join(matches), failed=False)
        except Exception as err:
            return ToolResult(f"Error executing find with pattern '{pattern}': {err}", failed=True)


class GrepTool(Tool):
    """在文件集合中按正则表达式或文本字面量快速搜索匹配行。"""

    name = "grep_search"
    description = (
        "Search for a regex or substring pattern inside text files. "
        "Returns matching file paths, line numbers, and matching lines."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The regular expression or substring to search for.",
            },
            "root_path": {
                "type": "string",
                "description": "Directory or file to search in. Defaults to '.'.",
            },
            "file_pattern": {
                "type": "string",
                "description": "Optional file glob filter (e.g. '*.py', '*.ts').",
            },
            "max_matches": {
                "type": "integer",
                "description": "Maximum matching lines to return. Defaults to 50.",
            },
        },
        "required": ["query"],
    }
    capability = ToolCapability(effect=ToolEffect.READ, concurrency_safe=True)

    async def execute(
        self,
        query: str,
        root_path: str = ".",
        file_pattern: str | None = None,
        max_matches: int = 50,
        **kwargs: Any,
    ) -> ToolResult:
        base = Path(root_path).resolve()
        if not base.exists():
            return ToolResult(f"Error: Target path '{root_path}' does not exist.", failed=True)

        try:
            regex = re.compile(query, re.IGNORECASE)
        except re.error as err:
            return ToolResult(f"Error: Invalid regular expression '{query}': {err}", failed=True)

        files_to_check: list[Path] = []
        if base.is_file():
            files_to_check.append(base)
        else:
            glob_pat = file_pattern or "**/*"
            for p in base.glob(glob_pat):
                if p.is_file():
                    parts = p.parts
                    if ".git" in parts or ".venv" in parts or "__pycache__" in parts or "node_modules" in parts:
                        continue
                    files_to_check.append(p)

        matches: list[str] = []
        for file in files_to_check:
            try:
                # 忽略超大文件和非文本
                if file.stat().st_size > 5 * 1024 * 1024:
                    continue
                content = file.read_text(encoding="utf-8", errors="ignore")
                for line_num, line in enumerate(content.splitlines(), start=1):
                    if regex.search(line):
                        rel = file.relative_to(base) if base.is_dir() else file.name
                        matches.append(f"{rel}:{line_num}: {line.strip()}")
                        if len(matches) >= max_matches:
                            break
                if len(matches) >= max_matches:
                    break
            except Exception:
                continue

        if not matches:
            return ToolResult(f"No occurrences of '{query}' found under '{root_path}'.", failed=False)

        header = f"Grep found {len(matches)} match(es) for '{query}':\n"
        return ToolResult(header + "\n".join(matches), failed=False)
