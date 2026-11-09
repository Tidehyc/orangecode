"""进化树存储与节点状态机。"""

from dataclasses import dataclass, field

from orangecode.evolver.candidate_manifest import CandidateManifest


@dataclass
class EvolutionNode:
    """进化树中的状态节点。"""

    node_id: str
    parent_id: str | None
    manifest: CandidateManifest | None = None
    score: float = 0.0
    visits: int = 0
    children_ids: list[str] = field(default_factory=list)

    @property
    def is_root(self) -> bool:
        return self.parent_id is None


class EvolutionTree:
    """进化树容器：维护所有节点状态与分支路径。"""

    def __init__(self, root_id: str = "root", baseline_score: float = 0.0) -> None:
        self.nodes: dict[str, EvolutionNode] = {}
        root = EvolutionNode(node_id=root_id, parent_id=None, score=baseline_score, visits=1)
        self.nodes[root_id] = root
        self.root_id = root_id

    def add_node(self, node_id: str, parent_id: str, manifest: CandidateManifest, score: float) -> EvolutionNode:
        """向指定父节点下添加子节点。"""
        if parent_id not in self.nodes:
            raise ValueError(f"Parent node '{parent_id}' does not exist in evolution tree.")

        node = EvolutionNode(
            node_id=node_id,
            parent_id=parent_id,
            manifest=manifest,
            score=score,
            visits=1,
        )
        self.nodes[node_id] = node
        self.nodes[parent_id].children_ids.append(node_id)
        return node

    def get_best_leaf(self) -> EvolutionNode:
        """获取全树中得分最高的分支节点。"""
        return max(self.nodes.values(), key=lambda n: n.score)
