"""沙箱执行器工厂。"""

from orangecode.sandbox.config import SandboxConfig
from orangecode.sandbox.direct_executor import DirectExecutor
from orangecode.sandbox.interfaces import CommandExecutor
from orangecode.sandbox.isolated_executor import IsolatedWorkspaceExecutor
from orangecode.sandbox.srt_executor import SRTExecutor


def build_executor(config: SandboxConfig) -> CommandExecutor:
    """根据配置实例化对应的安全执行器。"""
    backend = config.backend.lower()

    if backend in ("none", "direct"):
        return DirectExecutor()

    if backend == "isolated":
        return IsolatedWorkspaceExecutor(sandbox_root=config.workspace_dir)

    if backend == "srt":
        return SRTExecutor(
            workspace_dir=config.workspace_dir,
            allow_net=config.allow_net,
            read_only_root=config.read_only_root,
        )

    # 默认使用目录隔离
    return IsolatedWorkspaceExecutor(sandbox_root=config.workspace_dir)
