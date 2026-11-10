"""评估引擎 Orchestrator：管理评估依赖装配与自动化评测工作流。"""

from __future__ import annotations

from typing import Any

from orangecode.eval_engine.hooks import AgentHook, ToolAuditHook
from orangecode.eval_engine.judge import EvalJudge, JudgeVerdict
from orangecode.providers.base import LLMProvider


class EvalEngine:
    """自动化评估引擎，协调裁判模型与运行期审计钩子。"""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        pass_threshold: float = 0.7,
    ) -> None:
        self.provider = provider
        self.audit_hook = ToolAuditHook()
        self.judge = EvalJudge(provider=provider, pass_threshold=pass_threshold) if provider else None

    def get_hooks(self) -> list[AgentHook]:
        """导出当前评估装配的全部钩子。"""
        return [self.audit_hook]

    async def evaluate_task(
        self,
        query: str,
        response: str,
        reference: str | None = None,
    ) -> dict[str, Any]:
        """综合工具审计数据与裁判模型评分生成完整任务质量评估报告。"""
        verdict: JudgeVerdict | None = None
        if self.judge:
            verdict = await self.judge.judge(query=query, response=response, reference=reference)

        audit_summary = self.audit_hook.summary()
        return {
            "score": verdict.score if verdict else 1.0,
            "passed": verdict.passed if verdict else True,
            "reasoning": verdict.reasoning if verdict else "No LLM judge configured",
            "tool_audit": audit_summary,
        }
