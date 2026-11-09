"""沙箱执行环境的 Pydantic 配置规范。"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SandboxConfig(BaseModel):
    """沙箱环境配置模型。"""

    model_config = ConfigDict(extra="ignore")

    backend: Literal["none", "direct", "isolated", "srt", "boxlite"] = Field(
        default="isolated",
        description="沙箱后端模式：none/direct(直接宿主)、isolated(目录受限隔离)、srt(Anthropic SRT)、boxlite(微虚拟机)",
    )
    workspace_dir: Path = Field(
        default_factory=lambda: Path.cwd(),
        description="工作区根目录",
    )
    timeout_seconds: float = Field(default=60.0, description="单次命令执行超时硬上限（秒）")
    allow_net: bool = Field(default=True, description="是否允许网络出网请求")
    read_only_root: bool = Field(default=False, description="是否将沙箱根文件系统设为只读")
