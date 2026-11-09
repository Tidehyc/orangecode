"""KNN 语义模型路由器：按任务难度与成本收益动态派发最优模型。"""

import hashlib
from dataclasses import dataclass

import numpy as np

from orangecode.routing.profiles import DEFAULT_PROFILES
from orangecode.utils.bm25 import tokenize


@dataclass
class ExemplarTask:
    """路由范例样本数据结构。"""

    task_name: str
    text: str
    embedding: list[float]
    rewards: dict[str, float]  # 模型 -> 质量收益分 (0.0 - 1.0)
    costs: dict[str, float]    # 模型 -> 实际单次调用成本


def _text_to_pseudo_embedding(text: str, dim: int = 64) -> list[float]:
    """轻量哈希特征向量投影（在缺少专用向量模型时的确定性特征映射）。"""
    vec = np.zeros(dim, dtype=np.float32)
    tokens = tokenize(text)
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        val = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += val
    norm = np.linalg.norm(vec)
    if norm > 1e-6:
        vec = vec / norm
    return vec.tolist()


class KNNModelRouter:
    """基于 K 近邻价值评估的模型路由器。"""

    def __init__(
        self,
        exemplars: list[ExemplarTask] | None = None,
        k: int = 3,
        lambda_cost: float = 0.5,
        default_model: str = "deepseek/deepseek-chat",
    ) -> None:
        self.k = k
        self.lambda_cost = lambda_cost
        self.default_model = default_model
        self.exemplars: list[ExemplarTask] = exemplars or []

    def add_exemplar(self, task: ExemplarTask) -> None:
        """注册训练/校准范例。"""
        self.exemplars.append(task)

    def select_model(
        self,
        prompt: str,
        candidates: list[str] | None = None,
    ) -> tuple[str, float]:
        """为输入 Prompt 推荐最具性价比的目标大模型。

        返回 (推荐模型名, 综合效用得分)。
        若没有足够的范例证据，则安全回退到默认模型。
        """
        if not self.exemplars:
            return self.default_model, 0.0

        query_vec = np.array(_text_to_pseudo_embedding(prompt), dtype=np.float32)

        # 计算所有 Exemplars 的余弦相似度
        similarities: list[tuple[float, ExemplarTask]] = []
        for ex in self.exemplars:
            ex_vec = np.array(ex.embedding, dtype=np.float32)
            sim = float(np.dot(query_vec, ex_vec))
            similarities.append((sim, ex))

        # 取 Top-K 最近邻
        similarities.sort(key=lambda x: x[0], reverse=True)
        neighbors = similarities[: self.k]

        available_candidates = candidates or list(DEFAULT_PROFILES.keys())

        # 统计各候选模型在 Top-K 上的净效用得分: reward - lambda_cost * cost
        model_scores: dict[str, list[float]] = {m: [] for m in available_candidates}

        for sim, ex in neighbors:
            for model in available_candidates:
                reward = ex.rewards.get(model, 0.5)
                cost = ex.costs.get(model, 0.01)
                utility = reward - self.lambda_cost * cost
                # 按相似度加权
                model_scores[model].append(utility * max(0.1, sim))

        # 计算加权平均净收益
        best_model = self.default_model
        best_utility = -float("inf")

        for model, scores in model_scores.items():
            if scores:
                avg_util = sum(scores) / len(scores)
                if avg_util > best_utility:
                    best_utility = avg_util
                    best_model = model

        return best_model, float(best_utility)
