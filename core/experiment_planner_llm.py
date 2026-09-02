from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.llm_gateway import LLMGateway
from core.unified_schema import (
    CandidateExperiment,
    ExperimentStep,
    ProtocolRefinementSuggestion,
    ScientificTask,
)


class ExperimentPlannerLLMResponse(BaseModel):
    rationale: str = Field(min_length=1)
    suggested_model_parameters: dict[str, Any] = Field(default_factory=dict)
    suggested_feature_focus: list[str] = Field(default_factory=list)
    protocol_notes: list[str] = Field(default_factory=list)
    extra_steps: list[dict[str, Any]] = Field(default_factory=list)


class ExperimentPlannerLLM:
    """Refine a chosen candidate into a more explicit executable protocol suggestion."""

    SYSTEM_PROMPT = """你是“逐影 Shadow Tracing”的实验规划者。

你接收的是已经通过人工审批候选实验的结构化上下文。你的职责不是绕过程序生成整份协议，
而是在当前 candidate 的基础上给出结构化、可校验、可执行的 refinement 建议。

要求：
1. 不得发明不存在的 candidate_id、hypothesis_id、uncertainty_id
2. 只输出严格 JSON
3. 数值参数只给模型参数建议，不做最终裁决
4. 所有建议必须适合作为 protocol refinement 附加到现有协议上"""

    def __init__(self, *, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway or LLMGateway()

    def refine(
        self,
        *,
        task: ScientificTask,
        candidate: CandidateExperiment,
        existing_refinements: list[ProtocolRefinementSuggestion] | None = None,
    ) -> ProtocolRefinementSuggestion:
        response = self.gateway.generate_structured(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=self._build_user_prompt(
                task=task,
                candidate=candidate,
                existing_refinements=existing_refinements or [],
            ),
            response_model=ExperimentPlannerLLMResponse,
            fallback_factory=lambda: self._fallback(candidate),
        )
        return ProtocolRefinementSuggestion(
            suggestion_id="EPL001",
            target_candidate_id=candidate.experiment_id,
            refinement_type="llm_experiment_planner",
            rationale=response.rationale,
            suggested_model_parameters=_filter_model_parameters(response.suggested_model_parameters),
            suggested_feature_focus=[
                feature
                for feature in response.suggested_feature_focus
                if feature in candidate.design.treatment or feature in candidate.design.control
            ],
            suggested_steps=_coerce_steps(response.extra_steps),
            protocol_notes=["llm_experiment_planner"] + response.protocol_notes,
        )

    def _build_user_prompt(
        self,
        *,
        task: ScientificTask,
        candidate: CandidateExperiment,
        existing_refinements: list[ProtocolRefinementSuggestion],
    ) -> str:
        return (
            f"scientific_task={task.payload.research_question.text}\n"
            f"candidate_id={candidate.experiment_id}\n"
            f"candidate_type={candidate.type}\n"
            f"candidate_purpose={candidate.purpose}\n"
            f"tested_hypotheses={candidate.tested_hypotheses}\n"
            f"related_uncertainties={candidate.related_uncertainties}\n"
            f"control={candidate.design.control}\n"
            f"treatment={candidate.design.treatment}\n"
            f"candidate_notes={candidate.design.notes}\n"
            f"existing_refinements={[item.model_dump(exclude_none=True) for item in existing_refinements]}\n"
            "请输出 JSON: rationale, suggested_model_parameters, suggested_feature_focus, protocol_notes, extra_steps。"
        )

    @staticmethod
    def _fallback(candidate: CandidateExperiment) -> ExperimentPlannerLLMResponse:
        focus = candidate.design.treatment[:2]
        notes = [
            f"llm_planner_focus_candidate:{candidate.experiment_id}",
            "llm_planner_requests_pre_run_review",
        ]
        if candidate.related_uncertainties:
            notes.append(f"llm_planner_targets:{candidate.related_uncertainties[0]}")
        extra_steps = [
            {
                "action": "planner_hypothesis_focus",
                "parameters": {
                    "candidate_id": candidate.experiment_id,
                    "tested_hypotheses": candidate.tested_hypotheses,
                },
            }
        ]
        return ExperimentPlannerLLMResponse(
            rationale=f"针对 {candidate.experiment_id}，优先明确假设焦点和执行前检查，减少协议歧义。",
            suggested_model_parameters={"alpha": 0.22} if "validation" in candidate.type else {},
            suggested_feature_focus=focus,
            protocol_notes=notes,
            extra_steps=extra_steps,
        )


def _filter_model_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    allowed = {"window_size", "use_lag_feature", "max_lag_day", "alpha", "l1_ratio", "random_state"}
    filtered: dict[str, Any] = {}
    for key, value in parameters.items():
        if key not in allowed:
            continue
        if isinstance(value, (int, float, bool)):
            filtered[key] = value
    return filtered


def _coerce_steps(extra_steps: list[dict[str, Any]]) -> list[ExperimentStep]:
    steps: list[ExperimentStep] = []
    for index, item in enumerate(extra_steps, start=1):
        action = item.get("action")
        if not action:
            continue
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        steps.append(
            ExperimentStep(
                step=index,
                action=str(action),
                parameters=parameters,
            )
        )
    return steps
