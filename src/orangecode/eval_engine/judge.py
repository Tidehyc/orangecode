"""LLM-as-a-Judge 评估器：对 Agent 回复质量进行结构化打分与归因。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from loguru import logger

from orangecode.providers.base import LLMProvider


@dataclass
class JudgeVerdict:
    score: float  # 0.0 ~ 1.0
    passed: bool
    reasoning: str


class EvalJudge:
    """使用 LLM 作为裁判裁决输出质量。"""

    def __init__(
        self,
        provider: LLMProvider,
        pass_threshold: float = 0.7,
    ) -> None:
        self.provider = provider
        self.pass_threshold = pass_threshold

    async def judge(
        self,
        query: str,
        response: str,
        reference: str | None = None,
    ) -> JudgeVerdict:
        """评估 response 是否准确解决 query。"""
        judge_prompt = (
            "You are an expert evaluator assessing the quality of an AI agent's answer.\n"
            f"User Query:\n{query}\n\n"
            f"Agent Response:\n{response}\n\n"
        )
        if reference:
            judge_prompt += f"Reference / Expected Answer:\n{reference}\n\n"

        judge_prompt += (
            "Evaluate the correctness, completeness, and precision.\n"
            "Respond strictly in JSON format as follows:\n"
            '{"score": <float between 0.0 and 1.0>, "passed": <true/false>, "reasoning": "<concise explanation>"}'
        )

        messages = [
            {"role": "system", "content": "You are an objective judge evaluating AI outputs."},
            {"role": "user", "content": judge_prompt},
        ]

        llm_resp = await self.provider.chat_complete(messages=messages, temperature=0.0)
        content = llm_resp.content or ""

        # 解析 JSON 判决
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                score = float(data.get("score", 0.0))
                passed = bool(data.get("passed", score >= self.pass_threshold))
                reasoning = str(data.get("reasoning", "Parsed from judge output"))
                return JudgeVerdict(score=score, passed=passed, reasoning=reasoning)
            except Exception as e:
                logger.warning(f"Error parsing judge JSON: {e}")

        # 解析失败时的安全退化
        return JudgeVerdict(
            score=0.5,
            passed=False,
            reasoning=f"Could not parse structured judge verdict: {content[:200]}",
        )
