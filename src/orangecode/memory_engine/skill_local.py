"""本地技能库监视器：解析 SKILL.md Frontmatter 并加载技能。"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from loguru import logger


@dataclass
class SkillDefinition:
    """本地技能模型。"""

    name: str
    description: str
    instructions: str
    triggers: list[str] = field(default_factory=list)
    path: Path | None = None


class SkillWatcher:
    """扫描指定目录下的 SKILL.md 技能包。"""

    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.skills: dict[str, SkillDefinition] = {}
        self.scan()

    def scan(self) -> dict[str, SkillDefinition]:
        """扫描根目录并解析所有 SKILL.md。"""
        self.skills.clear()
        if not self.root_dir.exists():
            return self.skills

        for skill_file in self.root_dir.glob("**/SKILL.md"):
            try:
                content = skill_file.read_text(encoding="utf-8")
                # 正则提取 YAML Frontmatter
                match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
                if match:
                    frontmatter_str, instructions = match.group(1), match.group(2)
                    meta = yaml.safe_load(frontmatter_str) or {}
                else:
                    meta = {"name": skill_file.parent.name, "description": ""}
                    instructions = content

                name = meta.get("name", skill_file.parent.name)
                desc = meta.get("description", "")
                triggers = meta.get("triggers", [])

                skill = SkillDefinition(
                    name=name,
                    description=desc,
                    instructions=instructions.strip(),
                    triggers=triggers,
                    path=skill_file.parent,
                )
                self.skills[name] = skill
            except Exception as e:
                logger.error(f"Error parsing skill at {skill_file}: {e}")

        logger.info(f"SkillWatcher discovered {len(self.skills)} skill(s) under {self.root_dir}")
        return self.skills
