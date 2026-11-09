"""Evolver 候选改动元数据清单与评审分类。"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class CandidateLabel(StrEnum):
    """候选变体类别。"""

    SKILL = "skill"
    PROMPT = "prompt"
    POLICY = "policy"
    RUNTIME = "runtime"


@dataclass
class CandidateManifest:
    """一次进化候选变体清单。"""

    candidate_id: str
    label: CandidateLabel
    hypothesis: str
    diff_patch: str
    score_baseline: float = 0.0
    score_candidate: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "pending"  # "pending", "accepted", "rejected"

    @property
    def score_delta(self) -> float:
        """候选变体带来的收益增量。"""
        return self.score_candidate - self.score_baseline

    @property
    def is_improvement(self) -> bool:
        """是否带来净正向收益。"""
        return self.score_delta > 0.0
