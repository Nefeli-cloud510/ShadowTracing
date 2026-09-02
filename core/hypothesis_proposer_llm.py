from __future__ import annotations

from pydantic import BaseModel, Field

from core.llm_gateway import LLMGateway
from core.rag_service import RAGContextBundle
from core.unified_schema import ReasoningPlannerInput


class HypothesisProposerResponse(BaseModel):
    focus_features: list[str] = Field(default_factory=list)
    guidance_notes: list[str] = Field(default_factory=list)
    proposal_summaries: list[str] = Field(default_factory=list)


class HypothesisProposerLLM:
    """LLM-backed hypothesis proposer with safe local fallback."""

    SYSTEM_PROMPT = """你是“逐影 Shadow Tracing”的假设提出者。

你的任务是根据 planner_input 与 RAG 证据，给出下一轮值得扩展的假设方向提示。
不要直接修改状态，只输出结构化 JSON，供系统程序继续生成假设树。"""

    def __init__(self, *, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway or LLMGateway()

    def propose(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        rag_context: RAGContextBundle,
    ) -> HypothesisProposerResponse:
        return self.gateway.generate_structured(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=(
                f"planner_input={planner_input.to_central_controller_payload()}\n"
                f"rag_notes={rag_context.guidance_notes()}\n"
                "请输出 focus_features、guidance_notes、proposal_summaries。"
            ),
            response_model=HypothesisProposerResponse,
            fallback_factory=lambda: self._fallback(planner_input, rag_context),
        )

    @staticmethod
    def _fallback(
        planner_input: ReasoningPlannerInput,
        rag_context: RAGContextBundle,
    ) -> HypothesisProposerResponse:
        merged = " ".join(
            rag_context.guidance_notes()
            + planner_input.planner_guidance
            + [planner_input.human_feedback or ""]
        ).lower()
        focus_features = [
            feature
            for feature in planner_input.data_dictionary_summary.feature_candidates
            if feature.lower() in merged and feature != planner_input.target
        ][:3]
        notes = [
            f"proposer_focus:{feature} 可能构成下一轮假设扩展条件。"
            for feature in focus_features
        ]
        if rag_context.literature_evidence:
            notes.append(
                f"proposer_literature:{rag_context.literature_evidence[0].excerpt}"
            )
        summaries = [
            f"围绕 {feature} 扩展条件路径或机制分支。"
            for feature in focus_features
        ]
        if not summaries:
            summaries.append("保留当前主假设，同时生成一个更保守的竞争解释分支。")
        return HypothesisProposerResponse(
            focus_features=focus_features,
            guidance_notes=notes,
            proposal_summaries=summaries,
        )
