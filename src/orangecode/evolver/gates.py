"""统计显著性门禁：确保仅当改进具有统计证据时才激活合并。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GateVerdict:
    """门禁决策裁决。"""

    passed: bool
    baseline_mean: float
    candidate_mean: float
    delta: float
    reason: str


class StatisticalGate:
    """统计门禁评估器。"""

    def __init__(self, min_delta: float = 0.02, min_trials: int = 3) -> None:
        self.min_delta = min_delta
        self.min_trials = min_trials

    def evaluate(self, baseline_scores: list[float], candidate_scores: list[float]) -> GateVerdict:
        """评估候选变体对比基线的得分是否显著提升。"""
        if len(candidate_scores) < self.min_trials or len(baseline_scores) < self.min_trials:
            return GateVerdict(
                passed=False,
                baseline_mean=0.0,
                candidate_mean=0.0,
                delta=0.0,
                reason=f"Insufficient trial samples ({len(candidate_scores)} < {self.min_trials}).",
            )

        b_mean = sum(baseline_scores) / len(baseline_scores)
        c_mean = sum(candidate_scores) / len(candidate_scores)
        delta = c_mean - b_mean

        if delta < self.min_delta:
            return GateVerdict(
                passed=False,
                baseline_mean=b_mean,
                candidate_mean=c_mean,
                delta=delta,
                reason=f"Improvement delta ({delta:.4f}) does not meet threshold ({self.min_delta:.4f}).",
            )

        return GateVerdict(
            passed=True,
            baseline_mean=b_mean,
            candidate_mean=c_mean,
            delta=delta,
            reason=f"Candidate passed statistical gate with +{delta:.4f} gain.",
        )
