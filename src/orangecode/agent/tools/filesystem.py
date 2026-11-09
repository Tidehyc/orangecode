"""高阶文件系统工具集：读取（带行号切片）、写入、精确替换编辑与目录浏览。"""

from pathlib import Path
from typing import Any

from orangecode.agent.tools.base import Tool, ToolResult
from orangecode.agent.tools.execution import ToolCapability, ToolEffect


class ReadFileTool(Tool):
    """读取文件内容，支持指定起止行号切片并附带行号前缀。"""

    name = "read_file"
    description = (
        "Read the contents of a text file. Supports optional line range slicing "
        "(start_line and end_line). Returns line-numbered content for accurate editing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path of the file to read.",
            },
            "start_line": {
                "type": "integer",
                "description": "Optional 1-based start line number (inclusive).",
            },
            "end_line": {
                "type": "integer",
                "description": "Optional 1-based end line number (inclusive).",
            },
        },
        "required": ["path"],
    }
    capability = ToolCapability(effect=ToolEffect.READ, concurrency_safe=True)

    async def execute(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        file_path = Path(path).resolve()
        if not file_path.exists():
            return ToolResult(f"Error: File not found at '{path}'.", failed=True)
        if not file_path.is_file():
            return ToolResult(f"Error: Path '{path}' is not a regular file.", failed=True)

        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(lines)
            s = max(1, start_line) if start_line is not None else 1
            e = min(total_lines, end_line) if end_line is not None else total_lines

            if s > total_lines:
                return ToolResult(
                    f"Warning: start_line ({s}) exceeds total line count ({total_lines}). File is empty or range out of bounds.",
                    failed=False,
                )

            selected_lines = lines[s - 1 : e]
            numbered = [f"{s + idx:4d} | {line}" for idx, line in enumerate(selected_lines)]
            output = f"File: {path} (Showing lines {s}-{e} of {total_lines})\n" + "\n".join(numbered)
            return ToolResult(output, failed=False)
        except Exception as err:
            return ToolResult(f"Error reading file '{path}': {err}", failed=True)


class WriteFileTool(Tool):
    """创建或全量覆盖写入文件，自动创建不存在的父目录。"""

    name = "write_file"
    description = "Create a new file or overwrite an existing file with given text content."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path of the file to write.",
            },
            "content": {
                "type": "string",
                "description": "The full text content to write into the file.",
            },
        },
        "required": ["path", "content"],
    }
    capability = ToolCapability(effect=ToolEffect.WRITE, concurrency_safe=False)

    async def execute(self, path: str, content: str, **kwargs: Any) -> ToolResult:
        try:
            file_path = Path(path).resolve()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return ToolResult(
                f"Successfully wrote {len(content)} characters to '{path}'.",
                failed=False,
            )
        except Exception as err:
            return ToolResult(f"Error writing to file '{path}': {err}", failed=True)


class EditFileTool(Tool):
    """通过精确的目标字符串替换来编辑文件，确保修改的原子性。"""

    name = "edit_file"
    description = (
        "Edit an existing file by replacing an exact string 'target' with 'replacement'. "
        "The target string must match exactly, including indentation and whitespace."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path of the file to edit.",
            },
            "target": {
                "type": "string",
                "description": "The exact string segment to be replaced.",
            },
            "replacement": {
                "type": "string",
                "description": "The new replacement string.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Whether to replace all occurrences if target appears multiple times. Default false.",
            },
        },
        "required": ["path", "target", "replacement"],
    }
    capability = ToolCapability(effect=ToolEffect.WRITE, concurrency_safe=False)

    async def execute(
        self,
        path: str,
        target: str,
        replacement: str,
        replace_all: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        file_path = Path(path).resolve()
        if not file_path.exists():
            return ToolResult(f"Error: File '{path}' does not exist.", failed=True)

        try:
            content = file_path.read_text(encoding="utf-8")
            count = content.count(target)
            if count == 0:
                return ToolResult(
                    f"Error: Target string not found in '{path}'. Please verify whitespace and indentation.",
                    failed=True,
                )
            if count > 1 and not replace_all:
                return ToolResult(
                    f"Error: Target string occurs {count} times in '{path}'. Please provide more context to make target unique, or set replace_all=true.",
                    failed=True,
                )

            new_content = content.replace(target, replacement) if replace_all else content.replace(target, replacement, 1)
            file_path.write_text(new_content, encoding="utf-8")
            return ToolResult(
                f"Successfully replaced {count if replace_all else 1} occurrence(s) in '{path}'.",
                failed=False,
            )
        except Exception as err:
            return ToolResult(f"Error editing file '{path}': {err}", failed=True)


class ListDirTool(Tool):
    """列出指定目录下的文件与子目录清单。"""

    name = "list_dir"
    description = "List entries in a directory with file types and sizes."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The directory path to inspect. Defaults to current working directory.",
            },
        },
    }
    capability = ToolCapability(effect=ToolEffect.READ, concurrency_safe=True)

    async def execute(self, path: str = ".", **kwargs: Any) -> ToolResult:
        dir_path = Path(path).resolve()
        if not dir_path.exists():
            return ToolResult(f"Error: Directory '{path}' does not exist.", failed=True)
        if not dir_path.is_dir():
            return ToolResult(f"Error: Path '{path}' is not a directory.", failed=True)

        try:
            entries: list[str] = []
            for item in sorted(dir_path.iterdir()):
                prefix = "[DIR] " if item.is_dir() else "[FILE]"
                size_str = f" ({item.stat().st_size:,} bytes)" if item.is_file() else ""
                entries.append(f"{prefix} {item.name}{size_str}")

            header = f"Directory contents of '{path}' ({len(entries)} items):\n"
            return ToolResult(header + "\n".join(entries), failed=False)
        except Exception as err:
            return ToolResult(f"Error listing directory '{path}': {err}", failed=True)
