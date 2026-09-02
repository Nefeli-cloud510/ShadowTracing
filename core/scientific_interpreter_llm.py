from __future__ import annotations

from pydantic import BaseModel, Field

from core.llm_gateway import LLMGateway
from core.planner_unified import ProgrammaticPlannerOutputBuilder
from core.unified_schema import CandidateExperimentSet, InterpretationEnhancement, ReasoningPlannerInput


class ScientificInterpreterLLMResponse(BaseModel):
    target_hypothesis_id: str | None = None
    interpretation: str = Field(min_length=1)
    related_uncertainty_ids: list[str] = Field(default_factory=list)
    impact_direction: str = Field(default="clarifies")
    impact_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    uncertainty_priority_action: str = Field(default="maintain")
    suggested_state_note: str | None = None


class ScientificInterpreterLLM:
    """LLM scaffold for turning evaluation context into interpretation enhancements."""

    SYSTEM_PROMPT = """你是“逐影 Shadow Tracing”的科学解释者。

你要基于统一 planner_input 输出结构化解释增强，用于写回假设树和不确定性状态。
不能虚构不存在的 hypothesis_id 或 uncertainty_id，输出必须是严格 JSON。"""

    def __init__(
        self,
        *,
        gateway: LLMGateway | None = None,
        baseline_builder: ProgrammaticPlannerOutputBuilder | None = None,
    ) -> None:
        self.gateway = gateway or LLMGateway()
        self.baseline_builder = baseline_builder or ProgrammaticPlannerOutputBuilder()

    def build_interpretations(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        candidate_plan: CandidateExperimentSet,
    ) -> list[InterpretationEnhancement]:
        baseline_output = self.baseline_builder.build(
            planner_input=planner_input,
            candidate_plan=candidate_plan,
        )
        baseline = baseline_output.interpretation_enhancements
        response = self.gateway.generate_structured(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=(
                "请结合以下上下文输出一条结构化解释增强。\n"
                f"context={planner_input.to_scientific_interpreter_payload()}\n"
            ),
            response_model=ScientificInterpreterLLMResponse,
            fallback_factory=lambda: self._build_fallback_response(planner_input, baseline),
        )
        llm_enhancement = InterpretationEnhancement(
            enhancement_id="LIE_INT_001",
            target_hypothesis_id=_resolve_hypothesis_id(planner_input, response.target_hypothesis_id),
            interpretation=response.interpretation,
            evidence_basis=planner_input.evaluation_summary.key_findings[:2],
            related_uncertainties=_resolve_uncertainty_ids(
                planner_input,
                response.related_uncertainty_ids,
            ),
            suggested_state_note=response.suggested_state_note,
            impact_direction=_normalize_impact_direction(response.impact_direction),
            impact_strength=response.impact_strength,
            confidence=response.confidence,
            uncertainty_priority_action=_normalize_priority_action(
                response.uncertainty_priority_action
            ),
        )
        return baseline[:1] + [
            llm_enhancement
        ]

    @staticmethod
    def _build_fallback_response(
        planner_input: ReasoningPlannerInput,
        baseline: list[InterpretationEnhancement],
    ) -> ScientificInterpreterLLMResponse:
        top_hypothesis = planner_input.active_hypotheses[0] if planner_input.active_hypotheses else None
        top_uncertainty = planner_input.unresolved_uncertainties[0] if planner_input.unresolved_uncertainties else None
        baseline_interpretation = baseline[0].interpretation if baseline else "当前仍需保守解释。"
        return ScientificInterpreterLLMResponse(
            target_hypothesis_id=top_hypothesis.hypothesis_id if top_hypothesis else None,
            interpretation=baseline_interpretation,
            related_uncertainty_ids=[top_uncertainty.uncertainty_id] if top_uncertainty else [],
            impact_direction="supports"
            if planner_input.evaluation_summary.delta_pearson_r and planner_input.evaluation_summary.delta_pearson_r > 0
            else "clarifies",
            impact_strength=0.55,
            confidence=0.68,
            uncertainty_priority_action="maintain",
            suggested_state_note="scientific_interpreter_llm fallback",
        )


def _resolve_hypothesis_id(
    planner_input: ReasoningPlannerInput,
    requested_id: str | None,
) -> str | None:
    valid_ids = {item.hypothesis_id for item in planner_input.active_hypotheses}
    if requested_id in valid_ids:
        return requested_id
    return planner_input.active_hypotheses[0].hypothesis_id if planner_input.active_hypotheses else None


def _resolve_uncertainty_ids(
    planner_input: ReasoningPlannerInput,
    requested_ids: list[str],
) -> list[str]:
    valid_ids = {item.uncertainty_id for item in planner_input.unresolved_uncertainties}
    resolved = [item for item in requested_ids if item in valid_ids]
    if resolved:
        return resolved
    return [item.uncertainty_id for item in planner_input.unresolved_uncertainties[:2]]


def _normalize_impact_direction(direction: str) -> str:
    if direction in {"supports", "weakens", "clarifies"}:
        return direction
    return "clarifies"


def _normalize_priority_action(action: str) -> str:
    if action in {"increase", "decrease", "maintain"}:
        return action
    return "maintain"
