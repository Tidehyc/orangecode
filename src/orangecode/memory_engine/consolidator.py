"""两层长期记忆固化系统：时间化事件流 (episodes.md) 与用户画像快照 (user_profile.md)。"""

from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from orangecode.config import settings
from orangecode.providers.base import LLMProvider


class MemoryConsolidator:
    """会话记忆提炼与长期画像沉淀引擎。"""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        memory_dir: Path | None = None,
    ) -> None:
        self.provider = provider
        self.memory_dir = memory_dir or (settings.state_dir / "memory")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.episodes_file = self.memory_dir / "episodes.md"
        self.user_profile_file = self.memory_dir / "user_profile.md"

    def record_episode(self, summary: str, tags: list[str] | None = None) -> None:
        """记录一条时间戳事件到 episodes.md。"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tag_str = " ".join(f"#{t}" for t in (tags or []))
        entry = f"- [{now_str}] {summary.strip()} {tag_str}\n"

        with open(self.episodes_file, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.debug(f"Recorded memory episode: {summary[:60]}")

    def update_user_profile(self, key_fact: str) -> None:
        """向 user_profile.md 增量更新用户偏好。"""
        now_str = datetime.now().strftime("%Y-%m-%d")
        entry = f"- [{now_str}] {key_fact.strip()}\n"

        if not self.user_profile_file.exists():
            self.user_profile_file.write_text("# User Profile & Key Preferences\n\n", encoding="utf-8")

        with open(self.user_profile_file, "a", encoding="utf-8") as f:
            f.write(entry)

    def get_memory_context(self, max_episodes: int = 5) -> list[str]:
        """获取近期记忆条目供注入 System Prompt。"""
        memories: list[str] = []
        if self.user_profile_file.exists():
            lines = self.user_profile_file.read_text(encoding="utf-8").splitlines()
            for line in lines:
                if line.startswith("- ["):
                    memories.append(line[2:])

        if self.episodes_file.exists():
            lines = self.episodes_file.read_text(encoding="utf-8").splitlines()
            recent_episodes = [item[2:] for item in lines if item.startswith("- [")][-max_episodes:]
            memories.extend(recent_episodes)

        return memories

    async def consolidate_session(self, messages: list[dict[str, Any]]) -> str:
        """分析整轮会话并提炼出关键决策与用户事实。"""
        if not messages or not self.provider:
            return ""

        # 构造提炼分析 Prompt
        transcript = []
        for m in messages:
            role = m.get("role")
            if role in ("user", "assistant"):
                transcript.append(f"{role}: {m.get('content', '')[:300]}")

        prompt = (
            "Analyze the following conversation transcript. Extract 1-3 key factual facts, user preferences, "
            "or finalized project decisions that should be remembered in future sessions. Format each fact as a bullet point.\n\n"
            + "\n".join(transcript[-8:])
        )

        try:
            resp = await self.provider.chat_complete(
                messages=[
                    {"role": "system", "content": "You are a precise memory consolidation agent."},
                    {"role": "user", "content": prompt},
                ]
            )
            extracted = resp.content or ""
            for line in extracted.splitlines():
                clean_line = line.strip().lstrip("-* ").strip()
                if clean_line:
                    self.record_episode(summary=clean_line, tags=["auto_consolidated"])
            return extracted
        except Exception as e:
            logger.error(f"Error during memory consolidation: {e}")
            return ""
