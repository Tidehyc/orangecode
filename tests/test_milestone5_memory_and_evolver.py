"""测试 Milestone 5：两层长期记忆、SKILL.md 本地技能监视器、Evolver 进化树与 UCB 老虎机门禁。"""

from orangecode.evolver.bandit import TreeAwareBandit
from orangecode.evolver.candidate_manifest import CandidateLabel, CandidateManifest
from orangecode.evolver.gates import StatisticalGate
from orangecode.evolver.tree import EvolutionTree
from orangecode.memory_engine.consolidator import MemoryConsolidator
from orangecode.memory_engine.skill_local import SkillWatcher


def test_memory_consolidator_two_layer(tmp_path):
    mem_dir = tmp_path / "memory"
    consolidator = MemoryConsolidator(memory_dir=mem_dir)

    # 1. 记录时间化事件
    consolidator.record_episode("User fixed database connection timeout bug", tags=["db", "bugfix"])
    assert consolidator.episodes_file.exists()
    episodes_content = consolidator.episodes_file.read_text(encoding="utf-8")
    assert "User fixed database connection" in episodes_content
    assert "#db" in episodes_content

    # 2. 沉淀用户偏好
    consolidator.update_user_profile("User prefers using PostgreSQL over MySQL")
    assert consolidator.user_profile_file.exists()
    profile_content = consolidator.user_profile_file.read_text(encoding="utf-8")
    assert "User prefers using PostgreSQL" in profile_content

    # 3. 获取上下文注入记忆片段
    ctx = consolidator.get_memory_context()
    assert len(ctx) >= 2


def test_skill_watcher_parsing(tmp_path):
    skills_root = tmp_path / "skills"
    skill_a_dir = skills_root / "git-workflow"
    skill_a_dir.mkdir(parents=True)

    skill_content = (
        "---\n"
        "name: git-workflow\n"
        "description: Guide and automate Git branching and release workflows.\n"
        "triggers:\n"
        "  - git\n"
        "  - branch\n"
        "---\n\n"
        "# Git Workflow Instructions\n"
        "Always create feature branches off main.\n"
    )
    (skill_a_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

    watcher = SkillWatcher(root_dir=skills_root)
    assert "git-workflow" in watcher.skills
    skill = watcher.skills["git-workflow"]
    assert skill.name == "git-workflow"
    assert "automate Git" in skill.description
    assert "git" in skill.triggers
    assert "Always create feature branches" in skill.instructions


def test_evolution_tree_and_bandit():
    tree = EvolutionTree(root_id="root_0", baseline_score=0.80)

    # 添加变体 1: 弱提升 (0.81)
    m1 = CandidateManifest(
        candidate_id="cand_1",
        label=CandidateLabel.PROMPT,
        hypothesis="Improve clarity",
        diff_patch="...",
        score_baseline=0.80,
        score_candidate=0.81,
    )
    tree.add_node("node_1", parent_id="root_0", manifest=m1, score=0.81)

    # 添加变体 2: 强提升 (0.92)
    m2 = CandidateManifest(
        candidate_id="cand_2",
        label=CandidateLabel.RUNTIME,
        hypothesis="Add retry mechanism",
        diff_patch="...",
        score_baseline=0.80,
        score_candidate=0.92,
    )
    tree.add_node("node_2", parent_id="root_0", manifest=m2, score=0.92)

    # 校验最佳叶节点
    best_leaf = tree.get_best_leaf()
    assert best_leaf.node_id == "node_2"
    assert best_leaf.score == 0.92

    # 校验 UCB 老虎机选择
    bandit = TreeAwareBandit(exploration_weight=1.0)
    selected = bandit.select_node(tree)
    assert selected is not None


def test_statistical_gate():
    gate = StatisticalGate(min_delta=0.05, min_trials=3)

    baseline = [0.70, 0.72, 0.71]  # 均值 0.71
    candidate_pass = [0.82, 0.85, 0.84]  # 均值 0.836 -> delta ~ 0.126 > 0.05
    candidate_fail = [0.72, 0.73, 0.71]  # 均值 0.72 -> delta ~ 0.01 < 0.05

    verdict_ok = gate.evaluate(baseline, candidate_pass)
    assert verdict_ok.passed
    assert verdict_ok.delta > 0.05

    verdict_fail = gate.evaluate(baseline, candidate_fail)
    assert not verdict_fail.passed
