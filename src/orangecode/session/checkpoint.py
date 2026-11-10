"""工作区带外影子 Git 检查点管理与工作区漂移 (Workspace Drift) 检测系统。"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from loguru import logger

_GIT_IDENT = (
    "-c", "user.name=OrangeCode",
    "-c", "user.email=checkpoint@orangecode.local",
    "-c", "commit.gpgsign=false",
)

_DEFAULT_EXCLUDES = """\
# OrangeCode shadow-git default excludes
.orangecode/
__pycache__/
*.pyc
dist/
build/
.venv/
venv/
node_modules/
"""


class ShadowGitCheckpoint:
    """管理独立于用户主 Git 的带外影子仓库，用于工作区恢复与状态漂移检测。"""

    def __init__(self, workspace: Path, shadow_git_dir: Path | None = None) -> None:
        self.workspace = workspace.resolve()
        self.git_dir = shadow_git_dir or (self.workspace / ".orangecode" / "shadow_git")
        self._ready = False

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        cmd = [
            "git",
            f"--git-dir={self.git_dir}",
            f"--work-tree={self.workspace}",
            *args,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def ensure_init(self) -> bool:
        """初始化带外影子仓库与忽略规则。"""
        if self._ready:
            return True
        if not shutil.which("git"):
            logger.warning("git binary not found in PATH; checkpoint disabled.")
            return False

        try:
            if not (self.git_dir / "HEAD").exists():
                self.git_dir.mkdir(parents=True, exist_ok=True)
                rc, _, err = await self._run_git("init")
                if rc != 0:
                    logger.debug(f"Shadow git init failed: {err}")
                    return False

            # 配置排除规则与 GC
            exclude_file = self.git_dir / "info" / "exclude"
            exclude_file.parent.mkdir(parents=True, exist_ok=True)
            exclude_file.write_text(_DEFAULT_EXCLUDES, encoding="utf-8")

            await self._run_git("config", "gc.auto", "256")
            self._ready = True
            return True
        except Exception as e:
            logger.debug(f"Error initializing shadow git checkpoint: {e}")
            return False

    async def commit_turn(self, label: str) -> tuple[str | None, list[str]]:
        """为当前轮次完成的工作区状态创建快照提交，返回 (commit_id, changed_files)。"""
        if not await self.ensure_init():
            return None, []

        try:
            rc, _, err = await self._run_git("add", "-A")
            if rc != 0:
                logger.debug(f"Checkpoint add failed: {err}")
                return None, []

            # 检查是否有变更需要提交
            _, diff_out, _ = await self._run_git("diff", "--cached", "--name-only")
            changed = [line.strip() for line in diff_out.splitlines() if line.strip()]
            if not changed:
                # 无变更时返回当前 HEAD
                rc, head_out, _ = await self._run_git("rev-parse", "--short", "HEAD")
                return (head_out.strip() if rc == 0 else None), []

            rc, _, err = await self._run_git(*_GIT_IDENT, "commit", "-m", label)
            if rc != 0:
                logger.debug(f"Checkpoint commit failed: {err}")
                return None, []

            rc, out, _ = await self._run_git("rev-parse", "--short", "HEAD")
            cid = out.strip() if rc == 0 else None
            return cid, changed
        except Exception as e:
            logger.debug(f"Error in commit_turn: {e}")
            return None, []

    async def detect_drift(self, expected_commit: str | None = None) -> tuple[bool, str]:
        """检测工作区是否在任务中断或离线期间发生未经管理的外部漂移。

        Returns:
            (is_drifted, reason)
        """
        if not await self.ensure_init():
            return False, "Checkpoint not initialized"

        try:
            # 1. 检查是否存在未提交的工作树修改
            rc, status_out, _ = await self._run_git("status", "--porcelain")
            dirty_files = [line.strip() for line in status_out.splitlines() if line.strip()]
            if dirty_files:
                return True, f"Working tree has uncommitted external modifications: {len(dirty_files)} file(s)"

            # 2. 如果指定了预期的历史 checkpoint，比对当前 HEAD 是否漂移
            if expected_commit:
                rc, head_out, _ = await self._run_git("rev-parse", "--short", "HEAD")
                current_head = head_out.strip() if rc == 0 else ""
                if current_head != expected_commit and not current_head.startswith(expected_commit):
                    return True, f"Workspace commit diverged: expected {expected_commit}, got {current_head}"

            return False, "Workspace in sync with checkpoint"
        except Exception as e:
            logger.warning(f"Error detecting workspace drift: {e}")
            return False, str(e)
