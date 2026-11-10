"""渠道发件人白名单控制：默认拒绝 (Deny-by-default) 与白名单判定。"""

from __future__ import annotations

from collections.abc import Iterable

from loguru import logger

_warned_empty: set[str] = set()


def is_allowed(
    channel_name: str,
    sender_id: str | int | None,
    allow_list: Iterable[str] | None,
) -> bool:
    """判断指定发件人是否获准进入指定的渠道。

    - allow_list 为空或 None：默认拒绝 (Deny-by-default)；
    - allow_list 包含 "*"：通配允许所有人访问；
    - 其他情况：执行精确匹配。
    """
    if allow_list is None:
        _warn_empty_once(channel_name)
        return False

    allow_set = set(map(str, allow_list))
    if not allow_set:
        _warn_empty_once(channel_name)
        return False

    if "*" in allow_set:
        return True

    return str(sender_id) in allow_set


def _warn_empty_once(channel_name: str) -> None:
    if channel_name in _warned_empty:
        return
    _warned_empty.add(channel_name)
    logger.warning(f"Channel '{channel_name}': allow_list is empty — all incoming messages denied.")


def reset_warning_state() -> None:
    """仅供单元测试重置警告记录。"""
    _warned_empty.clear()
