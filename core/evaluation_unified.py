from __future__ import annotations

import json
from pathlib import Path

from core.support_update_rules import (
    compute_support_update_from_prediction,
    observed_delta_from_comparison,
    signal_from_metric_deltas,
    signal_strength,
)
from core.unified_schema import (
    BootstrapReport,
    DisagreementUpdate,
    EvidenceClaim,
    EvaluationResult,
    HypothesisAssessment,
    HypothesisPrediction,
    ExperimentProtocol,
    ExperimentResult,
    PerformanceMetrics,
    RobustnessOverall,
    RobustnessReport,
    ScientificEvaluation,
    TimeSliceReport,
)

EPSILON = 1e-8


def build_performance_metrics(result: ExperimentResult) -> PerformanceMetrics:
    baseline = _get_run(result, "baseline")
    treatment = _get_run(result, "treatment")
    baseline_rmse = baseline.metrics.rmse if baseline else None
    treatment_rmse = treatment.metrics.rmse if treatment else None
    pg_actual_signed = _compute_pg_actual_signed(
        baseline_rmse=baseline_rmse,
        treatment_rmse=treatment_rmse,
    )

    return PerformanceMetrics(
        experiment_id=result.experiment_id,
        round_id=result.round_id,
        baseline_rmse=baseline_rmse,
        baseline_mae=baseline.metrics.mae if baseline else None,
        baseline_pearson_r=baseline.metrics.pearson_r if baseline else None,
        baseline_skill=baseline.metrics.skill if baseline else None,
        treatment_rmse=treatment_rmse,
        treatment_mae=treatment.metrics.mae if treatment else None,
        treatment_pearson_r=treatment.metrics.pearson_r if treatment else None,
        treatment_skill=treatment.metrics.skill if treatment else None,
        pg_actual_signed=pg_actual_signed,
        pg_actual_clipped=min(max(pg_actual_signed, 0.0), 1.0),
        delta=result.comparison,
    )


def build_minimal_scientific_evaluation(
    result: ExperimentResult,
    *,
    protocol: ExperimentProtocol | None = None,
    remaining_uncertainties: list[dict] | None = None,
) -> ScientificEvaluation:
    evidence_for: list[EvidenceClaim] = []
    evidence_against: list[EvidenceClaim] = []
    assessments: list[HypothesisAssessment] = []
    disagreement_updates: list[DisagreementUpdate] = []

    rmse_delta = result.comparison.rmse
    pearson_delta = result.comparison.pearson_r
    improvement_signal = signal_from_metric_deltas(rmse_delta, pearson_delta)
    observed_delta = observed_delta_from_comparison(
        skill_delta=result.comparison.skill,
        pearson_delta=pearson_delta,
        rmse_delta=rmse_delta,
    )

    if improvement_signal == "supports":
        evidence_for.append(
            EvidenceClaim(
                claim="treatment 相比 baseline 带来更好的预测表现，说明新增实验条件可能包含有效信息。",
                strength=signal_strength(rmse_delta, pearson_delta),
                source="experiment_result.comparison",
            )
        )
    elif improvement_signal == "weakens":
        evidence_against.append(
            EvidenceClaim(
                claim="treatment 未优于 baseline，当前新增实验条件的增量信息尚不充分。",
                strength=signal_strength(rmse_delta, pearson_delta),
                source="experiment_result.comparison",
            )
        )
    else:
        evidence_for.append(
            EvidenceClaim(
                claim="本轮实验结果呈混合信号，需要结合更多实验或稳健性分析继续判断。",
                strength="medium",
                source="experiment_result.comparison",
            )
        )

    if protocol and protocol.tested_hypotheses:
        for hypothesis_id in protocol.tested_hypotheses:
            prediction = protocol.hypothesis_predictions.get(hypothesis_id)
            if prediction is not None:
                outcome = compute_support_update_from_prediction(
                    current_support=0.5,
                    expected_effect=prediction.expected_effect,
                    expected_range=prediction.expected_range,
                    observed_delta=observed_delta,
                )
                assessments.append(
                    HypothesisAssessment(
                        hypothesis_id=hypothesis_id,
                        support_before=outcome.support_before,
                        support_after=outcome.support_after,
                        status=outcome.status,
                        direction_matched=outcome.direction_matched,
                        magnitude_matched=outcome.magnitude_matched,
                        reason=_assessment_reason(
                            hypothesis_id,
                            prediction,
                            observed_delta,
                            outcome.direction_matched,
                            outcome.magnitude_matched,
                        ),
                    )
                )
            target_list = evidence_for if improvement_signal == "supports" else evidence_against
            target_list.append(
                EvidenceClaim(
                    claim=f"{hypothesis_id} 在本轮被间接检验，但仍缺少与方向/量级预测严格对齐的证据。",
                    strength="medium",
                    source="protocol.tested_hypotheses",
                )
            )

    if protocol and protocol.target_uncertainties:
        disagreement_updates = _build_disagreement_updates(protocol, assessments)

    unresolved_from_disagreement = [
        {
            "uncertainty_id": item.uncertainty_id,
            "question": _uncertainty_question_from_protocol(protocol, item.uncertainty_id) if protocol else item.uncertainty_id,
            "description": item.summary,
            "priority": "high" if item.resolution_status == "unresolved" else "medium",
        }
        for item in disagreement_updates
        if item.resolution_status != "resolved"
    ]
    merged_remaining = list(remaining_uncertainties or []) + unresolved_from_disagreement

    return ScientificEvaluation(
        experiment_id=result.experiment_id,
        round_id=result.round_id,
        hypothesis_assessments=assessments,
        disagreement_updates=disagreement_updates,
        evidence_summary={
            "new_evidence_for": evidence_for,
            "new_evidence_against": evidence_against,
            "remaining_uncertainties": merged_remaining,
        },
    )


def build_minimal_robustness_report(result: ExperimentResult) -> RobustnessReport:
    complete = result.status == "completed" and len(result.runs) >= 2
    rmse_delta = result.comparison.rmse
    pearson_delta = result.comparison.pearson_r
    mixed_signal = (
        rmse_delta is not None
        and pearson_delta is not None
        and ((rmse_delta < 0 and pearson_delta < 0) or (rmse_delta > 0 and pearson_delta > 0))
    )
    stable = complete and not mixed_signal
    recommendation = (
        "可以进入下一轮假设解释，但建议补充 bootstrap/time-slice 稳健性检验。"
        if stable
        else "建议先补充更多稳健性检验，再据此更新假设支持度。"
    )

    return RobustnessReport(
        bootstrap=BootstrapReport(stable=stable, n_iterations=0),
        time_slice=TimeSliceReport(stable=stable),
        overall=RobustnessOverall(
            stable=stable,
            concern=None if stable else "当前仅完成单次主实验比较，稳健性证据不足。",
        ),
        recommendation=recommendation,
    )


def evaluate_experiment(
    result: ExperimentResult,
    *,
    protocol: ExperimentProtocol | None = None,
    remaining_uncertainties: list[dict] | None = None,
) -> EvaluationResult:
    return EvaluationResult(
        metrics=build_performance_metrics(result),
        robustness=build_minimal_robustness_report(result),
        scientific=build_minimal_scientific_evaluation(
            result,
            protocol=protocol,
            remaining_uncertainties=remaining_uncertainties,
        ),
        visualizations=result.visualizations,
    )


def export_evaluation_result(evaluation: EvaluationResult, file_path: Path) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(evaluation.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_run(result: ExperimentResult, run_name: str):
    for run in result.runs:
        if run.name == run_name:
            return run
    return None


def _assessment_reason(
    hypothesis_id: str,
    prediction: HypothesisPrediction | None,
    observed_delta: float,
    direction_matched: bool | str,
    magnitude_matched: bool | str,
) -> str:
    if prediction is None:
        return f"{hypothesis_id} 缺少结构化预测范围，当前仅依据实验增量信号做最小判断。"
    return (
        f"{hypothesis_id} 预期效应为 {prediction.expected_effect}，"
        f"观测到的增量为 {observed_delta:.4f}；"
        f"direction_matched={direction_matched}, magnitude_matched={magnitude_matched}。"
    )


def _build_disagreement_updates(
    protocol: ExperimentProtocol,
    assessments: list[HypothesisAssessment],
) -> list[DisagreementUpdate]:
    assessment_index = {item.hypothesis_id: item for item in assessments}
    updates: list[DisagreementUpdate] = []
    for uncertainty_id in protocol.target_uncertainties:
        disagreement = protocol.disagreement_context.get(uncertainty_id, {})
        if not disagreement:
            continue
        before_scores = {
            hypothesis_id: (item.support_score if hasattr(item, "support_score") and item.support_score is not None else 0.5)
            for hypothesis_id, item in disagreement.items()
        }
        after_scores = {
            hypothesis_id: assessment_index[hypothesis_id].support_after
            if hypothesis_id in assessment_index
            else before_scores[hypothesis_id]
            for hypothesis_id in disagreement
        }
        sorted_after = sorted(after_scores.items(), key=lambda item: item[1], reverse=True)
        before_span = round(max(before_scores.values()) - min(before_scores.values()), 4) if before_scores else 0.0
        after_span = round(max(after_scores.values()) - min(after_scores.values()), 4) if after_scores else 0.0
        top_gap = round(sorted_after[0][1] - sorted_after[1][1], 4) if len(sorted_after) >= 2 else sorted_after[0][1]
        narrowed = after_span <= max(before_span - 0.03, before_span * 0.75)
        if top_gap >= 0.18 and sorted_after[0][1] >= 0.58:
            resolution_status = "resolved"
        elif narrowed or top_gap >= 0.10:
            resolution_status = "partially_resolved"
        else:
            resolution_status = "unresolved"
        unresolved_hypotheses = [
            hypothesis_id
            for hypothesis_id, score in after_scores.items()
            if sorted_after and sorted_after[0][1] - score < 0.12
        ]
        summary = (
            f"{uncertainty_id} before_span={before_span:.3f}, after_span={after_span:.3f}, "
            f"leading={sorted_after[0][0] if sorted_after else 'n/a'}, status={resolution_status}"
        )
        updates.append(
            DisagreementUpdate(
                uncertainty_id=uncertainty_id,
                compared_hypotheses=list(disagreement.keys()),
                support_span_before=before_span,
                support_span_after=after_span,
                narrowed=narrowed,
                resolution_status=resolution_status,
                leading_hypothesis_id=sorted_after[0][0] if sorted_after else None,
                unresolved_hypotheses=unresolved_hypotheses,
                summary=summary,
            )
        )
    return updates


def _uncertainty_question_from_protocol(protocol: ExperimentProtocol, uncertainty_id: str) -> str:
    for step in protocol.steps:
        if step.action == "resolve_disagreement" and step.parameters.get("uncertainty_id") == uncertainty_id:
            return step.parameters.get("question") or uncertainty_id
    return uncertainty_id


def _compute_pg_actual_signed(
    *,
    baseline_rmse: float | None,
    treatment_rmse: float | None,
) -> float:
    if baseline_rmse is None or treatment_rmse is None:
        return 0.0
    return (baseline_rmse - treatment_rmse) / max(baseline_rmse, EPSILON)
