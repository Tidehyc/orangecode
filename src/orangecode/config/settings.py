"""全局配置定义与加载，基于 pydantic-settings。"""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """OrangeCode 系统运行配置。"""

    model_config = SettingsConfigDict(
        env_prefix="ORANGECODE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 基础运行环境
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # 模型默认设置
    default_model: str = Field(
        default="deepseek/deepseek-chat",
        description="默认模型标识符（LiteLLM 兼容格式）",
    )
    api_key: str | None = Field(default=None, description="默认模型 API Key")
    api_base: str | None = Field(default=None, description="默认模型 Base URL")

    # 调度与超时
    default_timeout_seconds: float = 60.0
    max_tool_iterations: int = 20

    # 运行时数据与状态存储路径
    state_dir: Path = Field(
        default=Path("~/.orangecode").expanduser(),
        description="Session、Checkpoint 与 Cache 存储目录",
    )


settings = Settings()

__all__ = ["Settings", "settings"]
