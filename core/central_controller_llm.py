from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.llm_gateway import LLMGateway
from core.planner_unified import ProgrammaticPlannerOutputBuilder
from core.unified_schema import (
    CandidateExperimentSet,
    InterpretationEnhancement,
    PlannerCandidateSupplement,
    ProtocolRefinementSuggestion,
    ReasoningPlannerInput,
    ReasoningPlannerOutput,
)


class CentralControllerLLMResponse(BaseModel):
    summary: str = Field(min_length=1)
    candidate_focus_ids: list[str] = Field(default_factory=list)
    candidate_rationale: str = Field(min_length=1)
    target_hypothesis_id: str | None = None
    interpretation: str = Field(min_length=1)
    related_uncertainty_ids: list[str] = Field(default_factory=list)
    impact_direction: str = Field(default="clarifies")
    impact_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    uncertainty_priority_action: str = Field(default="maintain")
    feature_focus: list[str] = Field(default_factory=list)
    protocol_notes: list[str] = Field(default_factory=list)
    suggested_model_parameters: dict[str, Any] = Field(default_factory=dict)


class CentralControllerLLM:
    """LLM-backed central controller that refines planner output on top of a safe baseline."""

    SYSTEM_PROMPT = """你是“逐影 Shadow Tracing”的中央进程控制者。

你的任务是读取统一 planner_input 与候选实验计划，在不绕过 human PI 审批的前提下，
输出下一轮规划的结构化裁决。你不能发明不存在的 candidate_id、hypothesis_id、
uncertainty_id；你只能在给定候选计划范围内聚焦、解释与细化。

输出必须是严格 JSON，且字段必须完整。"""

    def __init__(
        self,
        *,
        gateway: LLMGateway | None = None,
        baseline_builder: ProgrammaticPlannerOutputBuilder | None = None,
    ) -> None:
        self.gateway = gateway or LLMGateway()
        self.baseline_builder = baseline_builder or ProgrammaticPlannerOutputBuilder()

    def build(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        candidate_plan: CandidateExperimentSet,
    ) -> ReasoningPlannerOutput:
        baseline_output = self.baseline_builder.build(
            planner_input=planner_input,
            candidate_plan=candidate_plan,
        )
        response = self.gateway.generate_structured(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=self._build_user_prompt(
                planner_input=planner_input,
                candidate_plan=candidate_plan,
                baseline_output=baseline_output,
            ),
            response_model=CentralControllerLLMResponse,
            fallback_factory=lambda: self._build_fallback_response(
                planner_input=planner_input,
                candidate_plan=candidate_plan,
                baseline_output=baseline_output,
            ),
        )
        return self._compose_output(
            planner_input=planner_input,
            candidate_plan=candidate_plan,
            baseline_output=baseline_output,
            llm_response=response,
        )

    def _build_user_prompt(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        candidate_plan: CandidateExperimentSet,
        baseline_output: ReasoningPlannerOutput,
    ) -> str:
        top_candidates = []
        for candidate in candidate_plan.candidates[:3]:
            top_candidates.append(
                {
                    "experiment_id": candidate.experiment_id,
                    "type": candidate.type,
                    "purpose": candidate.purpose,
                    "tested_hypotheses": candidate.tested_hypotheses,
                    "related_uncertainties": candidate.related_uncertainties,
                    "treatment": candidate.design.treatment,
                    "notes": candidate.design.notes[-4:],
                    "utility_score": candidate.utility_score,
                }
            )
        return (
            "请基于以下 planner 输入，为下一轮输出结构化裁决。\n"
            "你只能使用候选计划里已有的 id。\n\n"
            f"planner_input={planner_input.to_central_controller_payload()}\n\n"
            f"candidate_plan_top={top_candidates}\n\n"
            f"baseline_summary={baseline_output.summary}\n"
            f"baseline_protocol_refinement_count={len(baseline_output.protocol_refinements)}\n"
            "请输出 JSON，包括：summary、candidate_focus_ids、candidate_rationale、"
            "target_hypothesis_id、interpretation、related_uncertainty_ids、impact_direction、"
            "impact_strength、confidence、uncertainty_priority_action、feature_focus、"
            "protocol_notes、suggested_model_parameters。"
        )

    def _build_fallback_response(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        candidate_plan: CandidateExperimentSet,
        baseline_output: ReasoningPlannerOutput,
    ) -> CentralControllerLLMResponse:
        top_candidate = candidate_plan.top_candidate() or (
            candidate_plan.candidates[0] if candidate_plan.candidates else None
        )
        top_hypothesis = planner_input.active_hypotheses[0] if planner_input.active_hypotheses else None
        top_uncertainty = (
            planner_input.unresolved_uncertainties[0] if planner_input.unresolved_uncertainties else None
        )
        feature_focus = []
        feedback_text = (planner_input.human_feedback or "").lower()
        for feature in planner_input.data_dictionary_summary.feature_candidates:
            if feature.lower() in feedback_text:
                feature_focus.append(feature)
        return CentralControllerLLMResponse(
            summary=baseline_output.summary or "中央控制器采用本地基线策略生成下一轮规划。",
            candidate_focus_ids=[top_candidate.experiment_id] if top_candidate else [],
            candidate_rationale=(
                f"优先细化 {top_candidate.experiment_id}，因为它在当前候选计划中综合价值较高，且更贴近最近反馈。"
                if top_candidate
                else "当前无候选可供细化。"
            ),
            target_hypothesis_id=top_hypothesis.hypothesis_id if top_hypothesis else None,
            interpretation=(
                f"结合上一轮评价与当前分歧，继续围绕 {top_hypothesis.hypothesis_id} 做更保守、可验证的下一轮推进。"
                if top_hypothesis
                else "当前没有明确活跃假设，优先保持探索性规划。"
            ),
            related_uncertainty_ids=[top_uncertainty.uncertainty_id] if top_uncertainty else [],
            impact_direction="supports"
            if planner_input.evaluation_summary.delta_pearson_r and planner_input.evaluation_summary.delta_pearson_r > 0
            else "clarifies",
            impact_strength=0.58 if planner_input.evaluation_summary.stable is not False else 0.42,
            confidence=0.72 if planner_input.evaluation_summary.stable is not False else 0.55,
            uncertainty_priority_action=(
                "decrease"
                if planner_input.evaluation_summary.delta_pearson_r
                and planner_input.evaluation_summary.delta_pearson_r > 0
                and planner_input.evaluation_summary.stable is not False
                else "maintain"
            ),
            feature_focus=feature_focus,
            protocol_notes=["llm_fallback_controller"],
            suggested_model_parameters={"alpha": 0.2} if feature_focus else {},
        )

    def _compose_output(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        candidate_plan: CandidateExperimentSet,
        baseline_output: ReasoningPlannerOutput,
        llm_response: CentralControllerLLMResponse,
    ) -> ReasoningPlannerOutput:
        candidate_index = {candidate.experiment_id: candidate for candidate in candidate_plan.candidates}
        valid_hypothesis_ids = {item.hypothesis_id for item in planner_input.active_hypotheses}
        valid_uncertainty_ids = {item.uncertainty_id for item in planner_input.unresolved_uncertainties}

        focused_candidates = [
            candidate_index[candidate_id]
            for candidate_id in llm_response.candidate_focus_ids
            if candidate_id in candidate_index
        ]
        if not focused_candidates:
            focused_candidates = [
                item.candidate.model_copy(deep=True) for item in baseline_output.candidate_supplements[:2]
            ]
        else:
            focused_candidates = [candidate.model_copy(deep=True) for candidate in focused_candidates[:2]]

        candidate_supplements: list[PlannerCandidateSupplement] = []
        for index, candidate in enumerate(focused_candidates, start=1):
            for feature in llm_response.feature_focus:
                note = f"llm_controller_feature_focus:{feature}"
                if note not in candidate.design.notes:
                    candidate.design.notes.append(note)
            if "llm_controller_selected" not in candidate.design.notes:
                candidate.design.notes.append("llm_controller_selected")
            candidate_supplements.append(
                PlannerCandidateSupplement(
                    proposal_id=f"LCP{index:03d}",
                    candidate=candidate,
                    rationale=llm_response.candidate_rationale,
                    source="central_controller_llm",
                )
            )

        target_hypothesis_id = (
            llm_response.target_hypothesis_id
            if llm_response.target_hypothesis_id in valid_hypothesis_ids
            else (planner_input.active_hypotheses[0].hypothesis_id if planner_input.active_hypotheses else None)
        )
        related_uncertainties = [
            uncertainty_id
            for uncertainty_id in llm_response.related_uncertainty_ids
            if uncertainty_id in valid_uncertainty_ids
        ]
        if not related_uncertainties:
            related_uncertainties = [
                item.uncertainty_id for item in planner_input.unresolved_uncertainties[:2]
            ]

        interpretation_enhancements = list(baseline_output.interpretation_enhancements)
        interpretation_enhancements.insert(
            0,
            InterpretationEnhancement(
                enhancement_id="LIE001",
                target_hypothesis_id=target_hypothesis_id,
                interpretation=llm_response.interpretation,
                evidence_basis=planner_input.evaluation_summary.key_findings[:2],
                related_uncertainties=related_uncertainties,
                suggested_state_note="由中央控制 LLM 生成的解释聚焦。",
                impact_direction=_normalize_impact_direction(llm_response.impact_direction),
                impact_strength=llm_response.impact_strength,
                confidence=llm_response.confidence,
                uncertainty_priority_action=_normalize_priority_action(
                    llm_response.uncertainty_priority_action
                ),
            ),
        )

        protocol_refinements = list(baseline_output.protocol_refinements)
        target_candidate_id = (
            candidate_supplements[0].candidate.experiment_id if candidate_supplements else None
        )
        protocol_refinements.insert(
            0,
            ProtocolRefinementSuggestion(
                suggestion_id="LPR001",
                target_candidate_id=target_candidate_id,
                refinement_type="llm_central_controller",
                rationale=llm_response.candidate_rationale,
                suggested_model_parameters=_filter_model_parameters(
                    llm_response.suggested_model_parameters
                ),
                suggested_feature_focus=[
                    feature
                    for feature in llm_response.feature_focus
                    if feature in planner_input.data_dictionary_summary.feature_candidates
                ],
                protocol_notes=["llm_central_controller"] + llm_response.protocol_notes,
            )
        )

        return ReasoningPlannerOutput(
            task_id=planner_input.task_id,
            source_round_id=planner_input.source_round_id,
            next_round_id=planner_input.next_round_id,
            source_experiment_id=planner_input.source_experiment_id,
            planner_mode="llm",
            candidate_supplements=candidate_supplements,
            interpretation_enhancements=interpretation_enhancements,
            protocol_refinements=protocol_refinements,
            summary=llm_response.summary,
        )


def _normalize_impact_direction(direction: str) -> str:
    if direction in {"supports", "weakens", "clarifies"}:
        return direction
    return "clarifies"


def _normalize_priority_action(action: str) -> str:
    if action in {"increase", "decrease", "maintain"}:
        return action
    return "maintain"


def _filter_model_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    allowed = {"window_size", "use_lag_feature", "max_lag_day", "alpha", "l1_ratio", "random_state"}
    filtered: dict[str, Any] = {}
    for key, value in parameters.items():
        if key not in allowed:
            continue
        if isinstance(value, (int, float, bool)):
            filtered[key] = value
    return filtered
