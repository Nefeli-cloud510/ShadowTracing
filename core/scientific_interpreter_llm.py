from __future__ import annotations

from pydantic import BaseModel, Field

from core.llm_gateway import LLMGateway
from core.prompt_rules import ELASTIC_NET_EXECUTION_RULE
from core.planner_unified import ProgrammaticPlannerOutputBuilder
from core.unified_schema import (
    CandidateExperimentSet,
    ConclusionDataLayer,
    InterpretationEnhancement,
    ReasoningPlannerInput,
)


class ScientificInterpreterLLMResponse(BaseModel):
    target_hypothesis_id: str | None = None
    interpretation: str = Field(min_length=1)
    related_uncertainty_ids: list[str] = Field(default_factory=list)
    impact_direction: str = Field(default="clarifies")
    impact_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    uncertainty_priority_action: str = Field(default="maintain")
    suggested_state_note: str | None = None
    rmse_attribution: str | None = None
    pearson_attribution: str | None = None
    skill_delta_meaning: str | None = None
    anomaly_identification: str | None = None
    next_focus: str | None = None
    conclusion_text: str | None = None


class InterpreterRoundAnalysis(BaseModel):
    """Combined output used by the round-report four-layer writer."""

    enhancements: list[InterpretationEnhancement]
    data_layer: ConclusionDataLayer | None = None
    conclusion_text: str | None = None


class ScientificInterpreterLLM:
    """LLM scaffold for turning evaluation context into interpretation enhancements."""

    SYSTEM_PROMPT = """你是“逐影 Shadow Tracing”的科学解释者。

你要基于统一 planner_input 输出结构化解释增强，用于写回假设树和不确定性状态。
不能虚构不存在的 hypothesis_id 或 uncertainty_id，输出必须是严格 JSON。
你必须同时覆盖两类解释：
1. 预测性能解释：重点分析 Vsw/目标变量 的 Pearson r、RMSE、相对对照组变化，以及趋势是否改善。
2. 科学假设解释：判断方向匹配、幅度匹配、失败归因与下一轮建议。
如果结果不理想，优先指出数据问题、特征问题、模型问题、假设问题、实验设计问题中的最可能项。""" + "\n\n" + ELASTIC_NET_EXECUTION_RULE

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
        return self.build_round_analysis(
            planner_input=planner_input,
            candidate_plan=candidate_plan,
        ).enhancements

    def build_round_analysis(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        candidate_plan: CandidateExperimentSet,
    ) -> InterpreterRoundAnalysis:
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
        return InterpreterRoundAnalysis(
            enhancements=self._build_enhancement(planner_input, baseline, response),
            data_layer=self._build_data_layer(response),
            conclusion_text=response.conclusion_text,
        )

    def _build_enhancement(
        self,
        planner_input: ReasoningPlannerInput,
        baseline: list[InterpretationEnhancement],
        response: ScientificInterpreterLLMResponse,
    ) -> list[InterpretationEnhancement]:
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
    def _build_data_layer(
        response: ScientificInterpreterLLMResponse,
    ) -> ConclusionDataLayer | None:
        if not any(
            [
                response.rmse_attribution,
                response.pearson_attribution,
                response.skill_delta_meaning,
                response.anomaly_identification,
                response.next_focus,
            ]
        ):
            return None
        return ConclusionDataLayer(
            rmse_attribution=response.rmse_attribution,
            pearson_attribution=response.pearson_attribution,
            skill_delta_meaning=response.skill_delta_meaning,
            anomalies=[response.anomaly_identification]
            if response.anomaly_identification
            else [],
            next_focus=response.next_focus,
        )

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
            interpretation=(
                f"{baseline_interpretation} 同时需要补充目标变量预测效果分析："
                f"关注 Pearson r 相对对照组的变化、RMSE 是否下降，以及当前结果对 Vsw 预测是否形成真实增益。"
            ),
            rmse_attribution=(
                f"RMSE 变化需要结合数据覆盖、特征覆盖与过拟合风险继续归因："
                f"当前 ΔRMSE={_format_delta(planner_input.evaluation_summary.delta_rmse)}，"
                "若训练集与测试集差异明显，指标变化更可能来自覆盖范围而非新增特征。"
            ),
            pearson_attribution=(
                f"Pearson r 反映整体趋势捕捉能力："
                f"当前 ΔPearson r={_format_delta(planner_input.evaluation_summary.delta_pearson_r)}，"
                "若改善较小，说明新增条件主要改变误差分布而非趋势相关性。"
            ),
            skill_delta_meaning=(
                "该增量表示实验组相对对照组的预测技能变化；"
                "只有同时满足幅度稳定与方向一致时，才具有实际预测意义。"
            ),
            anomaly_identification=(
                "需要继续核对 RMSE 与 Pearson r 是否出现方向不一致，"
                "并检查数据缺口、缺失对齐与异常样本是否集中在特定时间窗。"
            ),
            next_focus=(
                "下一轮优先围绕数据覆盖与路径变量的协同作用做区分实验，"
                "先排除数据质量问题再更新假设支持度。"
            ),
            conclusion_text=(
                "本轮实验结果需要先放在数据层做归因：当前指标增量尚未形成稳定的科学判断，"
                "建议结合样本覆盖与稳健性检验后再决定假设是否获得支持。"
            ),
            related_uncertainty_ids=[top_uncertainty.uncertainty_id] if top_uncertainty else [],
            impact_direction="supports"
            if planner_input.evaluation_summary.delta_pearson_r and planner_input.evaluation_summary.delta_pearson_r > 0
            else "clarifies",
            impact_strength=0.55,
            confidence=0.68,
            uncertainty_priority_action="maintain",
            suggested_state_note="scientific_interpreter_llm fallback",
        )


def _format_delta(value: float | None) -> str:
    if value is None:
        return "未取得"
    return f"{value:+.4f}"


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
