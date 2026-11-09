"""沙箱执行接口与结构化结果定义。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecResult:
    """命令执行结果封装。"""

    stdout: str
    stderr: str
    exit_code: int

    def as_text(self, max_chars: int = 8000) -> str:
        """格式化为适合送入 LLM 上下文的文本表达，并对过长输出自动截断。"""
        parts: list[str] = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr.strip():
            parts.append(f"STDERR:\n{self.stderr}")
        parts.append(f"Exit code: {self.exit_code}")
        full_text = "\n".join(parts)

        if len(full_text) > max_chars:
            half = max_chars // 2
            omitted = len(full_text) - max_chars
            return (
                f"{full_text[:half]}\n\n"
                f"... [{omitted} characters truncated] ...\n\n"
                f"{full_text[-half:]}"
            )
        return full_text


class CommandExecutor(ABC):
    """命令执行器的抽象基类。"""

    is_sandboxed: bool = False

    @abstractmethod
    async def execute(
        self,
        command: str,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> ExecResult:
        """异步执行命令并返回结果。"""
        raise NotImplementedError
