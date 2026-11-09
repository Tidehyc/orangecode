"""统一日志管理模块。"""

import sys

from loguru import logger


def setup_logger(level: str = "INFO") -> None:
    """初始化 Loguru 日志输出格式。"""
    logger.remove()
    logger.add(
        sys.stderr,
        level=level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )


# 默认配置一次 INFO 级别日志
setup_logger("INFO")

__all__ = ["logger", "setup_logger"]
