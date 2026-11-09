"""受限工作区沙箱执行器。"""

from pathlib import Path

from loguru import logger

from orangecode.sandbox.direct_executor import DirectExecutor
from orangecode.sandbox.interfaces import CommandExecutor, ExecResult


class IsolatedWorkspaceExecutor(CommandExecutor):
    """约束在特定沙箱根目录下的隔离执行器。"""

    is_sandboxed = True

    def __init__(self, sandbox_root: Path | str) -> None:
        self.sandbox_root = Path(sandbox_root).resolve()
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self._executor = DirectExecutor()

    async def execute(
        self,
        command: str,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> ExecResult:
        # 严格限制运行目录在 sandbox_root 之内
        target_cwd = (self.sandbox_root / (cwd or "")).resolve()
        if not str(target_cwd).startswith(str(self.sandbox_root)):
            logger.warning(f"Prevented path traversal outside sandbox: {target_cwd}")
            target_cwd = self.sandbox_root

        # 构造沙箱专属环境变量，隔绝敏感凭据并重定向临时目录
        sandboxed_env = {
            "HOME": str(self.sandbox_root),
            "TMPDIR": str(self.sandbox_root / ".tmp"),
            "ORANGECODE_SANDBOX": "1",
        }
        (self.sandbox_root / ".tmp").mkdir(exist_ok=True)
        if env:
            sandboxed_env.update(env)

        return await self._executor.execute(
            command=command,
            cwd=target_cwd,
            env=sandboxed_env,
            timeout=timeout,
        )
