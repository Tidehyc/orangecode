"""测试上下文引擎：Token 估算、BM25 检索、原子闭包与预算裁剪。"""

from orangecode.context.assembler import ContextAssembler
from orangecode.context.budget import TokenBudget
from orangecode.context.trimmer import HistoryTrimmer
from orangecode.utils.bm25 import BM25Okapi
from orangecode.utils.token_counter import estimate_prompt_tokens


def test_token_counter():
    # 测试 Tiktoken 计数
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you today?"},
    ]
    tokens = estimate_prompt_tokens(messages)
    assert tokens > 0
    assert 10 <= tokens <= 25


def test_bm25_cjk_search():
    # 测试中文与英文混合 BM25 检索
    corpus = [
        "Python 是一种广泛使用的高级编程语言，常用于后端和人工智能开发。",
        "Rust 是一门注重安全和性能的系统级编程语言，内存安全无 GC。",
        "Agent Harness 提供任务调度、上下文管理和沙箱工具执行能力。",
    ]
    bm25 = BM25Okapi(corpus)

    # 检索 "智能体 调度"
    results = bm25.search_top_k("Agent 调度 沙箱", k=1)
    assert len(results) == 1
    top_doc_idx, score = results[0]
    assert top_doc_idx == 2
    assert score > 0.0

    # 检索 "内存安全"
    results_rust = bm25.search_top_k("内存安全", k=1)
    assert len(results_rust) == 1
    assert results_rust[0][0] == 1


def test_trimmer_canonical_closure():
    # 测试工具调用的双向闭包与结构验证
    messages = [
        {"role": "user", "content": "Run tool test"},  # 0
        {
            "role": "assistant",  # 1
            "content": "Calling tool",
            "tool_calls": [{"id": "call_123", "type": "function", "function": {"name": "test"}}],
        },
        {"role": "tool", "tool_call_id": "call_123", "content": "result 123"},  # 2
        {"role": "assistant", "content": "Done"},  # 3
    ]

    # 1. 验证没有结构错误
    assert HistoryTrimmer.structural_errors(messages) == []

    # 2. 闭包算法：若传入了 [0, 2]（用户与工具结果），必须自动补齐中间的父级 assistant [1]
    closure = HistoryTrimmer.canonical_ids(messages, [0, 2])
    assert closure == [0, 1, 2]

    # 3. 若只传入 [2]（没有 user 消息存活），不可伪造起点，必须返回 []
    assert HistoryTrimmer.canonical_ids(messages, [2]) == []

    # 4. 构造破损结构并测试错误检测
    broken_messages = [
        {"role": "tool", "tool_call_id": "orphan_call_999", "content": "orphan"},
    ]
    errors = HistoryTrimmer.structural_errors(broken_messages)
    assert len(errors) == 1
    assert "no parent assistant tool_call" in errors[0]


def test_trimmer_tool_compaction():
    # 测试旧轮次过长工具输出的自动压缩
    long_content = "X" * 3000
    messages = [
        # 第 1 轮
        {"role": "user", "content": "Old turn"},
        {"role": "tool", "tool_call_id": "call_old", "content": long_content},
        # 第 2 轮（最新轮次）
        {"role": "user", "content": "Recent turn"},
        {"role": "tool", "tool_call_id": "call_recent", "content": long_content},
    ]

    compacted = HistoryTrimmer.compact_tool_results(messages, max_chars=500, keep_recent_turns=1)

    # 旧轮次的工具结果应被折叠压缩
    assert "[... Output truncated" in compacted[1]["content"]
    assert len(compacted[1]["content"]) < 1000

    # 最新一轮的工具结果应原样保留，供模型即时观察
    assert compacted[3]["content"] == long_content


def test_budget_trimming_drop_oldest_turn():
    # 测试超出 Token 预算时，自动按整轮从最旧丢弃
    # 限制 context_window 为 50，max_prompt 约为 30
    budget = TokenBudget(context_window=50, reserved_output=20, reserved_system=5, reserved_memory=0)
    trimmer = HistoryTrimmer(budget=budget)

    # 构造跨多轮的长历史，Token 远超 30
    messages = [
        {"role": "system", "content": "System identity"},
        # 轮次 1（旧，应被裁剪）
        {"role": "user", "content": "First long query " + "word " * 50},
        {"role": "assistant", "content": "First answer " + "word " * 50},
        # 轮次 2（新，应当被保留）
        {"role": "user", "content": "Second query"},
    ]

    outcome = trimmer.trim(messages)
    assert outcome.dropped_turns_count >= 1

    # 保留的消息中应包含 system 和最新的 user query
    roles = [m["role"] for m in outcome.messages]
    assert "system" in roles
    assert outcome.messages[-1]["content"] == "Second query"


def test_context_assembler():
    budget = TokenBudget()
    assembler = ContextAssembler(budget=budget)

    history = [
        {"role": "user", "content": "Previous question"},
        {"role": "assistant", "content": "Previous answer"},
    ]
    memories = ["User prefers Python over C++.", "User timezone is UTC+8."]

    messages, outcome = assembler.assemble(
        system_prompt="You are a coding assistant.",
        history=history,
        current_prompt="Write a quick script",
        memories=memories,
    )

    assert outcome.ok
    assert messages[0]["role"] == "system"
    assert "User prefers Python" in messages[0]["content"]
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "Write a quick script"
