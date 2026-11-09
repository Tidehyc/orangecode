"""并发隔离池：保障真实用户请求不被后台批量任务饥饿阻塞。"""

import asyncio

from orangecode.spine.turn import Origin


class OriginPools:
    """按 Origin 划分的并发信号量池。"""

    def __init__(self, user_limit: int = 10, system_limit: int = 5) -> None:
        self._user_sem = asyncio.Semaphore(user_limit)
        self._system_sem = asyncio.Semaphore(system_limit)

    def get_semaphore(self, origin: Origin) -> asyncio.Semaphore:
        """获取指定 Origin 对应的并发控制信号量。"""
        if origin == Origin.USER:
            return self._user_sem
        if origin in (Origin.CRON, Origin.SUBAGENT):
            return self._system_sem
        raise ValueError(f"Unknown origin: {origin}")
