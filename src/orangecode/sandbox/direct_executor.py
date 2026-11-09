"""宿主直接执行器（非沙箱，直接运行在指定工作目录）。"""

import asyncio
import os
from pathlib import Path

from loguru import logger

from orangecode.sandbox.interfaces import CommandExecutor, ExecResult


class DirectExecutor(CommandExecutor):
    """直接在宿主环境通过子进程执行命令。"""

    is_sandboxed = False

    async def execute(
        self,
        command: str,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> ExecResult:
        work_dir = str(cwd) if cwd else None
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        logger.debug(f"DirectExecutor running: {command} in cwd={work_dir}")
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=merged_env,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                stdout_str = stdout_bytes.decode("utf-8", errors="replace")
                stderr_str = stderr_bytes.decode("utf-8", errors="replace")
                return ExecResult(
                    stdout=stdout_str,
                    stderr=stderr_str,
                    exit_code=proc.returncode if proc.returncode is not None else -1,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                return ExecResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout} seconds.",
                    exit_code=124,
                )
        except Exception as e:
            return ExecResult(
                stdout="",
                stderr=f"Failed to spawn process: {e}",
                exit_code=1,
            )
