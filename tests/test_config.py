"""测试配置加载与日志。"""

from orangecode.config.settings import Settings
from orangecode.utils.logger import logger, setup_logger


def test_default_settings():
    s = Settings()
    assert s.environment == "development"
    assert s.max_tool_iterations == 20
    assert s.default_model == "deepseek/deepseek-chat"


def test_override_settings(monkeypatch):
    monkeypatch.setenv("ORANGECODE_DEFAULT_MODEL", "gpt-4o")
    monkeypatch.setenv("ORANGECODE_MAX_TOOL_ITERATIONS", "10")
    s = Settings()
    assert s.default_model == "gpt-4o"
    assert s.max_tool_iterations == 10


def test_logger_setup():
    setup_logger("DEBUG")
    logger.debug("Logger debug message test")
