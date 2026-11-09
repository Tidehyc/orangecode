"""常用内置工具集：文件读写与终端命令执行。"""

import asyncio
from pathlib import Path
from typing import Any

from orangecode.agent.tools.base import Tool, ToolResult


class ReadFileTool(Tool):
    """读取指定路径文件内容的工具。"""

    name = "read_file"
    description = "Read the contents of a text file from the filesystem."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The absolute or relative path of the file to read.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, path: str, **kwargs: Any) -> ToolResult:
        file_path = Path(path).resolve()
        if not file_path.exists():
            return ToolResult(f"Error: File not found at '{path}'.", failed=True)
        if not file_path.is_file():
            return ToolResult(f"Error: Path '{path}' is not a regular file.", failed=True)
        try:
            content = file_path.read_text(encoding="utf-8")
            return ToolResult(content, failed=False)
        except Exception as e:
            return ToolResult(f"Error reading file '{path}': {e}", failed=True)


class WriteFileTool(Tool):
    """向指定路径写入文件内容的工具。"""

    name = "write_file"
    description = "Create or overwrite a file with given text content."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path of the file to write.",
            },
            "content": {
                "type": "string",
                "description": "The text content to write into the file.",
            },
        },
        "required": ["path", "content"],
    }

    async def execute(self, path: str, content: str, **kwargs: Any) -> ToolResult:
        try:
            file_path = Path(path).resolve()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return ToolResult(f"Successfully wrote {len(content)} characters to '{path}'.", failed=False)
        except Exception as e:
            return ToolResult(f"Error writing to file '{path}': {e}", failed=True)


class BashTool(Tool):
    """在宿主或沙箱环境中执行 Shell 命令的工具。"""

    name = "execute_bash"
    description = "Execute a shell command asynchronously and return its stdout, stderr, and exit code."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The command string to execute in bash shell.",
            },
        },
        "required": ["command"],
    }
    timeout_seconds = 60.0

    async def execute(self, command: str, **kwargs: Any) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode

            output = f"Exit code: {exit_code}\n"
            if stdout_str:
                output += f"--- stdout ---\n{stdout_str}\n"
            if stderr_str:
                output += f"--- stderr ---\n{stderr_str}\n"

            return ToolResult(output.strip(), failed=(exit_code != 0))
        except Exception as e:
            return ToolResult(f"Error executing command '{command}': {e}", failed=True)
