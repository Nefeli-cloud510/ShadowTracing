from __future__ import annotations

from pydantic import BaseModel, Field

from core.llm_gateway import LLMGateway
from core.rag_service import RAGContextBundle
from core.unified_schema import ReasoningPlannerInput


class ProposedUncertainty(BaseModel):
    uncertainty_id: str | None = None
    question: str = Field(min_length=1)
    description: str = Field(min_length=1)
    priority: str = Field(default="medium", min_length=1)


class ScientificQuestionerResponse(BaseModel):
    challenge_points: list[str] = Field(default_factory=list)
    guidance_notes: list[str] = Field(default_factory=list)
    proposed_uncertainties: list[ProposedUncertainty] = Field(default_factory=list)


class ScientificQuestionerLLM:
    """LLM-backed scientific questioner that turns evidence gaps into explicit uncertainties."""

    SYSTEM_PROMPT = """你是“逐影 Shadow Tracing”的科学质询者。

你的任务是识别当前闭环中的证据缺口、替代解释和仍需验证的问题，并输出结构化 JSON。
不要直接修改状态文件，只给出 challenge_points、guidance_notes、proposed_uncertainties。"""

    def __init__(self, *, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway or LLMGateway()

    def question(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        rag_context: RAGContextBundle,
    ) -> ScientificQuestionerResponse:
        return self.gateway.generate_structured(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=(
                f"planner_input={planner_input.to_central_controller_payload()}\n"
                f"rag_notes={rag_context.guidance_notes()}\n"
                "请输出 challenge_points、guidance_notes、proposed_uncertainties。"
            ),
            response_model=ScientificQuestionerResponse,
            fallback_factory=lambda: self._fallback(planner_input, rag_context),
        )

    @staticmethod
    def _fallback(
        planner_input: ReasoningPlannerInput,
        rag_context: RAGContextBundle,
    ) -> ScientificQuestionerResponse:
        uncertainties: list[ProposedUncertainty] = []
        challenges: list[str] = []
        notes: list[str] = []
        if planner_input.evaluation_summary.stable is False:
            challenges.append("上一轮结果稳定性不足，当前结论可能依赖特定时间窗或滞后设定。")
            uncertainties.append(
                ProposedUncertainty(
                    question="上一轮增益是否只在局部时间窗口成立？",
                    description="需要增加时间片或稳定性验证，避免把局部提升误判为普遍规律。",
                    priority="high",
                )
            )
        if rag_context.project_evidence:
            notes.append(f"questioner_project:{rag_context.project_evidence[0].excerpt}")
        if rag_context.literature_evidence:
            notes.append(f"questioner_literature:{rag_context.literature_evidence[0].excerpt}")
        if planner_input.recent_disagreement_updates:
            item = planner_input.recent_disagreement_updates[0]
            challenges.append(f"{item.uncertainty_id} 仍未完全解决，应继续设计区分性验证。")
            uncertainties.append(
                ProposedUncertainty(
                    question=f"{item.uncertainty_id} 的领先假设是否经得起更简单验证？",
                    description=item.summary,
                    priority="medium",
                )
            )
        if not uncertainties:
            uncertainties.append(
                ProposedUncertainty(
                    question="当前主假设是否存在尚未显式建模的替代解释？",
                    description="需要补充一个竞争性不确定性，避免闭环只沿单一路径收敛。",
                    priority="medium",
                )
            )
        return ScientificQuestionerResponse(
            challenge_points=challenges or ["当前证据仍需通过竞争解释和稳健性验证进一步约束。"],
            guidance_notes=notes,
            proposed_uncertainties=uncertainties,
        )
