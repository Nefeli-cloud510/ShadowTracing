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
所有变量名必须严格来自 data_dictionary_summary 中已有字段，不允许发明新变量。
请尽量覆盖更多高价值字段，不要只围绕 1-2 个变量反复改写；优先同时给出独立增量、中介路径、调节/边界条件、竞争解释等不同类型的分支方向。
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
        mentioned = [
            feature
            for feature in planner_input.data_dictionary_summary.feature_candidates
            if feature.lower() in merged and feature != planner_input.target
        ]
        remaining = [
            feature
            for feature in planner_input.data_dictionary_summary.feature_candidates
            if feature not in mentioned and feature != planner_input.target
        ]
        focus_features = [*mentioned, *remaining[: max(0, 6 - len(mentioned))]][:6]
        notes = [
            f"proposer_focus:{feature} 可能构成下一轮假设扩展条件。"
            for feature in focus_features
        ]
        if rag_context.literature_evidence:
            notes.append(
                f"proposer_literature:{rag_context.literature_evidence[0].excerpt}"
            )
        summaries: list[str] = []
        for index, feature in enumerate(focus_features):
            mode = index % 4
            if mode == 0:
                summaries.append(f"围绕 {feature} 扩展独立增量或直接作用分支。")
            elif mode == 1:
                summaries.append(f"围绕 {feature} 扩展中介机制或传导路径分支。")
            elif mode == 2:
                summaries.append(f"围绕 {feature} 扩展边界条件或调节作用分支。")
            else:
                summaries.append(f"围绕 {feature} 扩展竞争解释或替代机制分支。")
        if not summaries:
            summaries.append("保留当前主假设，同时生成一个更保守的竞争解释分支。")
        return HypothesisProposerResponse(
            focus_features=focus_features,
            guidance_notes=notes,
            proposal_summaries=summaries,
        )
