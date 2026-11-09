"""多臂老虎机 (Tree-Aware UCB Bandit) 搜索策略。"""

import math

from orangecode.evolver.tree import EvolutionNode, EvolutionTree


class TreeAwareBandit:
    """基于 UCB1 的树感知多臂老虎机分支选择器。"""

    def __init__(self, exploration_weight: float = 1.414) -> None:
        self.c = exploration_weight

    def select_node(self, tree: EvolutionTree) -> EvolutionNode:
        """从进化树中挑选下一个最值得探索/利用的节点进行变异衍生。"""
        total_visits = sum(n.visits for n in tree.nodes.values())
        if total_visits <= 0:
            return tree.nodes[tree.root_id]

        best_node: EvolutionNode | None = None
        best_ucb = -float("inf")

        for node in tree.nodes.values():
            if node.visits == 0:
                return node

            # 计算 UCB 得分: 收益期望 + 探索置信区间奖励
            exploration_bonus = self.c * math.sqrt(2 * math.log(total_visits) / node.visits)
            ucb_value = node.score + exploration_bonus

            if ucb_value > best_ucb:
                best_ucb = ucb_value
                best_node = node

        return best_node or tree.nodes[tree.root_id]
