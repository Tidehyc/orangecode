"""Anthropic SRT (Sandbox Runtime Toolkit) 操作系统级安全沙箱执行器。"""

import shutil
from pathlib import Path

from loguru import logger

from orangecode.sandbox.direct_executor import DirectExecutor
from orangecode.sandbox.interfaces import CommandExecutor, ExecResult


class SRTExecutor(CommandExecutor):
    """基于 Anthropic SRT 工具包的强隔离沙箱。"""

    is_sandboxed = True

    def __init__(
        self,
        workspace_dir: Path | str,
        allow_net: bool = True,
        read_only_root: bool = False,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
        self.allow_net = allow_net
        self.read_only_root = read_only_root
        self._executor = DirectExecutor()

    def _probe_srt_available(self) -> bool:
        """检查宿主环境是否已安装 srt 二进制工具。"""
        return shutil.which("srt") is not None

    async def execute(
        self,
        command: str,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> ExecResult:
        if not self._probe_srt_available():
            err_msg = (
                "Anthropic SRT binary 'srt' not found on PATH. "
                "Refusing to execute command without mandatory OS sandbox boundary."
            )
            logger.error(err_msg)
            return ExecResult(stdout="", stderr=err_msg, exit_code=127)

        # 组装 srt 隔离运行命令
        work_dir = str(cwd or self.workspace_dir)
        srt_args: list[str] = ["srt", "run"]

        if not self.allow_net:
            srt_args.append("--no-net")
        if self.read_only_root:
            srt_args.append("--read-only")

        srt_args.extend(["--dir", work_dir, "--", "bash", "-c", command])
        wrapped_command = " ".join(f'"{arg}"' if " " in arg else arg for arg in srt_args)

        return await self._executor.execute(
            command=wrapped_command,
            cwd=work_dir,
            env=env,
            timeout=timeout,
        )
