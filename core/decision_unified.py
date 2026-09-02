from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.state_repository import UnifiedStateRepository
from core.unified_schema import (
    CandidateExperiment,
    CandidateExperimentSet,
    DataDictionary,
    EstimatedValue,
    ExperimentDesign,
    ExperimentMemoryState,
    HypothesisPrediction,
    HypothesisTreeState,
    PrioritizedUncertainty,
    PriorityFactors,
    RejectedCandidate,
    ReasoningPlannerInput,
    ScientificTask,
    UncertaintyDisagreement,
    UncertaintyPriorityQueue,
    UncertaintyRecord,
    UncertaintyState,
)

EPSILON = 1e-8


@dataclass(frozen=True)
class PlanningContext:
    guidance_text: str | None = None
    preferred_features: tuple[str, ...] = ()
    preferred_keywords: tuple[str, ...] = ()
    prefer_simple_design: bool = False


class UncertaintyPrioritizer:
    """Programmatic prioritizer that scores open scientific uncertainties."""

    def prioritize(
        self,
        uncertainty_state: UncertaintyState,
        hypothesis_tree: HypothesisTreeState,
    ) -> UncertaintyPriorityQueue:
        _refresh_uncertainty_disagreement(uncertainty_state, hypothesis_tree)
        node_index = hypothesis_tree.node_index()
        queue: list[PrioritizedUncertainty] = []

        for record in uncertainty_state.records:
            if record.status in {"resolved", "deprecated"}:
                continue

            related_scores = [
                node_index[hypothesis_id].support_score
                for hypothesis_id in record.related_hypotheses
                if hypothesis_id in node_index
            ]
            support_gap = (max(related_scores) - min(related_scores)) if len(related_scores) >= 2 else (
                related_scores[0] if related_scores else 0.3
            )
            hypothesis_count = len(record.related_hypotheses)
            expected_information_gain = min(
                1.0,
                0.35 + 0.15 * hypothesis_count + 0.2 * (1.0 if "independent" in record.question.lower() else 0.0),
            )
            estimated_cost = _estimate_uncertainty_cost(record)
            override = record.priority_factors.human_priority_override if record.priority_factors else None

            record.priority_factors = PriorityFactors(
                hypothesis_count=hypothesis_count,
                support_gap=round(min(max(support_gap, 0.0), 1.0), 4),
                expected_information_gain=round(expected_information_gain, 4),
                estimated_cost=round(estimated_cost, 4),
                human_priority_override=override,
            )
            priority_score = _combine_priority(record.priority, record.priority_factors, record.resolution_status)
            queue.append(
                PrioritizedUncertainty(
                    uncertainty_id=record.uncertainty_id,
                    question=record.question,
                    priority_score=priority_score,
                    status=record.status,
                    estimated_resolution_round=uncertainty_state.current_round + 1,
                )
            )

        queue = sorted(queue, key=lambda item: item.priority_score, reverse=True)
        uncertainty_state.priority_queue = UncertaintyPriorityQueue(
            last_updated=datetime.now(),
            current_round=uncertainty_state.current_round,
            queue=queue,
            resolved=[item.uncertainty_id for item in uncertainty_state.records if item.status == "resolved"],
            deprecated=[item.uncertainty_id for item in uncertainty_state.records if item.status == "deprecated"],
        )
        return uncertainty_state.priority_queue


class CandidateExperimentGenerator:
    """Generate a minimal set of candidate experiments from prioritized uncertainties."""

    def generate(
        self,
        *,
        task: ScientificTask,
        data_dictionary: DataDictionary,
        hypothesis_tree: HypothesisTreeState,
        uncertainty_state: UncertaintyState,
        experiment_memory: ExperimentMemoryState | None = None,
        planning_context: PlanningContext | None = None,
        limit: int = 3,
    ) -> CandidateExperimentSet:
        planning_context = planning_context or PlanningContext()
        _refresh_uncertainty_disagreement(uncertainty_state, hypothesis_tree)
        variables = task.payload.research_question.variables
        target = task.payload.research_question.target
        primary_x = variables.x if variables else (data_dictionary.feature_candidates[0] if data_dictionary.feature_candidates else target)
        mediator_candidates = variables.m_candidates if variables else []
        feature_pool = [item for item in data_dictionary.feature_candidates if item != primary_x]
        control_base = _unique_preserve_order(mediator_candidates + feature_pool[:2])
        queue = uncertainty_state.priority_queue or UncertaintyPriorityQueue(
            last_updated=datetime.now(),
            current_round=uncertainty_state.current_round,
            queue=[],
        )
        top_uncertainties = queue.top_uncertainties(limit=limit)
        node_index = hypothesis_tree.node_index()
        candidates: list[CandidateExperiment] = [
            CandidateExperiment(
                experiment_id=f"E_R{uncertainty_state.current_round + 1:02d}_00",
                type="baseline_benchmark",
                purpose="maintain benchmark and provide calibrated baseline for this round",
                scientific_question=f"在不新增 {primary_x} 的情况下，本轮基线性能表现如何？",
                tested_hypotheses=[],
                design=ExperimentDesign(
                    target=target,
                    control=control_base,
                    treatment=control_base,
                    notes=["baseline benchmark candidate"],
                ),
                requires_human_review=False,
                novelty="benchmark",
            )
        ]
        rejected_candidates: list[RejectedCandidate] = []
        top_uncertainties = _rank_uncertainties_with_feedback(top_uncertainties, uncertainty_state, planning_context)

        for offset, item in enumerate(top_uncertainties, start=1):
            record = uncertainty_state.record_index().get(item.uncertainty_id)
            if record is None:
                continue

            design = _design_from_uncertainty(record, target, primary_x, control_base, planning_context, node_index)
            rationale_context = _candidate_rationale_context(record, node_index)
            candidate = CandidateExperiment(
                experiment_id=f"E_R{uncertainty_state.current_round + 1:02d}_{offset:02d}",
                type=_candidate_type(record),
                purpose=_candidate_purpose(record, rationale_context),
                scientific_question=record.question,
                tested_hypotheses=record.related_hypotheses,
                related_uncertainties=[record.uncertainty_id],
                disagreement_context={
                    record.uncertainty_id: {
                        hypothesis_id: disagreement.model_copy(deep=True)
                        if hasattr(disagreement, "model_copy")
                        else disagreement
                        for hypothesis_id, disagreement in record.disagreement.items()
                    }
                },
                hypothesis_source_context=_candidate_source_context(record, node_index),
                design=design,
                hypothesis_predictions=_build_hypothesis_predictions(record, node_index),
                distinguishing_insight=_distinguishing_insight(record, rationale_context, primary_x),
                estimated_information_gain=EstimatedValue(
                    value=min(1.0, item.priority_score),
                    rationale=_information_gain_rationale(record, rationale_context),
                ),
                estimated_performance_gain=EstimatedValue(
                    value=_estimate_performance_gain(record, primary_x, experiment_memory),
                    rationale=_performance_gain_rationale(record, primary_x, experiment_memory),
                ),
                estimated_risk=EstimatedValue(
                    value=_estimate_candidate_risk(record),
                    rationale="复杂滞后或中介检验通常风险更高。",
                ),
                estimated_cost=EstimatedValue(
                    value=_estimate_candidate_cost(record),
                    rationale="更多变量和滞后窗口通常带来更高执行成本。",
                ),
                requires_human_review=True,
                novelty=_build_candidate_novelty(planning_context),
            )
            candidate.design.notes.extend(_planning_notes(planning_context))
            candidate.design.notes.extend(_rationale_design_notes(record, rationale_context))
            _annotate_candidate_estimates(
                candidate=candidate,
                task=task,
                data_dictionary=data_dictionary,
                hypothesis_tree=hypothesis_tree,
                experiment_memory=experiment_memory,
                current_round=uncertainty_state.current_round + 1,
            )
            candidates.append(candidate)

        if len(candidates) < 3:
            fallback_candidate = CandidateExperiment(
                experiment_id=f"E_R{uncertainty_state.current_round + 1:02d}_S1",
                type="sensitivity_probe",
                purpose=f"test lag sensitivity of {primary_x}",
                scientific_question=f"{primary_x} 的时间滞后设定是否影响实验结论稳定性？",
                tested_hypotheses=_collect_hypothesis_ids(top_uncertainties, uncertainty_state),
                related_uncertainties=[item.uncertainty_id for item in top_uncertainties[:2]],
                design=ExperimentDesign(
                    target=target,
                    control=control_base,
                    treatment=_unique_preserve_order(control_base + [primary_x]),
                    lags={primary_x: [1, 2, 3]},
                    notes=["fallback sensitivity probe to ensure candidate diversity"],
                ),
                requires_human_review=True,
                distinguishing_insight=(
                    f"通过时滞敏感性实验，区分这些假设来源是否只是时间设定差异造成，"
                    f"并继续检验 {primary_x} 的稳健性。"
                ),
                novelty="fallback candidate to satisfy minimum diversity",
            )
            fallback_candidate.design.notes.append("hypothesis_triggers:fallback_sensitivity_probe")
            _annotate_candidate_estimates(
                candidate=fallback_candidate,
                task=task,
                data_dictionary=data_dictionary,
                hypothesis_tree=hypothesis_tree,
                experiment_memory=experiment_memory,
                current_round=uncertainty_state.current_round + 1,
            )
            candidates.append(fallback_candidate)

        for candidate in candidates:
            if candidate.estimated_information_gain is None:
                _annotate_candidate_estimates(
                    candidate=candidate,
                    task=task,
                    data_dictionary=data_dictionary,
                    hypothesis_tree=hypothesis_tree,
                    experiment_memory=experiment_memory,
                    current_round=uncertainty_state.current_round + 1,
                )

        if experiment_memory:
            seen_ids = {entry.experiment_id for entry in experiment_memory.entries}
            for candidate in list(candidates):
                if candidate.experiment_id in seen_ids:
                    candidates.remove(candidate)
                    rejected_candidates.append(
                        RejectedCandidate(
                            experiment_id=candidate.experiment_id,
                            reason="experiment_id already exists in experiment_memory",
                            similar_to=candidate.experiment_id,
                        )
                    )

        return CandidateExperimentSet(
            round=uncertainty_state.current_round + 1,
            generated_at=datetime.now(),
            candidates=candidates,
            rejected_candidates=rejected_candidates,
            minimum_required=3,
            note=_candidate_set_note(len(candidates), planning_context),
        )


class UtilityScorer:
    """Compute simplified utility scores for candidate experiments."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or {
            "alpha": 0.50,
            "beta": 0.20,
            "gamma": 0.20,
            "delta": 0.10,
        }

    def score(self, candidate_set: CandidateExperimentSet) -> CandidateExperimentSet:
        beta = 0.0 if candidate_set.round <= 1 else self.weights["beta"]
        for candidate in candidate_set.candidates:
            ig = candidate.estimated_information_gain.value if candidate.estimated_information_gain else 0.0
            pg = candidate.estimated_performance_gain.value if candidate.estimated_performance_gain else 0.0
            risk = candidate.estimated_risk.value if candidate.estimated_risk else 0.5
            cost = candidate.estimated_cost.value if candidate.estimated_cost else 0.5
            utility = (
                self.weights["alpha"] * ig
                + beta * pg
                - self.weights["gamma"] * risk
                - self.weights["delta"] * cost
            )
            candidate.utility_score = round(min(max(utility, 0.0), 1.0), 4)
        candidate_set.candidates.sort(key=lambda item: item.utility_score or 0.0, reverse=True)
        return candidate_set


class DecisionLayerService:
    """End-to-end procedural decision layer for the first non-LLM planning stage."""

    def __init__(
        self,
        repository: UnifiedStateRepository,
        prioritizer: UncertaintyPrioritizer | None = None,
        generator: CandidateExperimentGenerator | None = None,
        scorer: UtilityScorer | None = None,
    ) -> None:
        self.repository = repository
        self.prioritizer = prioritizer or UncertaintyPrioritizer()
        self.generator = generator or CandidateExperimentGenerator()
        self.scorer = scorer or UtilityScorer()

    def build_candidate_plan(
        self,
        *,
        task: ScientificTask,
        data_dictionary: DataDictionary,
        planning_feedback: str | None = None,
        planner_input: ReasoningPlannerInput | None = None,
    ) -> CandidateExperimentSet:
        tree = self.repository.load_hypothesis_tree()
        uncertainties = self.repository.load_uncertainties()
        experiment_memory = self.repository.load_experiment_memory()
        merged_feedback = planning_feedback or (planner_input.merged_guidance_text() if planner_input else None)
        planning_context = _build_planning_context(merged_feedback, data_dictionary)
        prioritized = self.prioritizer.prioritize(uncertainties, tree)
        candidates = self.generator.generate(
            task=task,
            data_dictionary=data_dictionary,
            hypothesis_tree=tree,
            uncertainty_state=uncertainties,
            experiment_memory=experiment_memory,
            planning_context=planning_context,
        )
        scored = self.scorer.score(candidates)
        uncertainties.priority_queue = prioritized
        self.repository.save_uncertainties(uncertainties)
        self.repository.save_candidate_experiments(scored)
        return scored


def _refresh_uncertainty_disagreement(
    uncertainty_state: UncertaintyState,
    hypothesis_tree: HypothesisTreeState,
) -> None:
    node_index = hypothesis_tree.node_index()
    for record in uncertainty_state.records:
        if not record.related_hypotheses:
            continue
        disagreement: dict[str, UncertaintyDisagreement] = {}
        for hypothesis_id in record.related_hypotheses:
            node = node_index.get(hypothesis_id)
            if node is None:
                continue
            disagreement[hypothesis_id] = UncertaintyDisagreement(
                hypothesis_id=hypothesis_id,
                expected=_expected_from_node(node),
                status=node.status,
                support_score=node.support_score,
                rationale_trigger=node.generation_rationale.trigger if node.generation_rationale else None,
                source_summary=node.generation_rationale.summary if node.generation_rationale else None,
            )
        record.disagreement = disagreement


def _combine_priority(
    priority: str,
    factors: PriorityFactors,
    resolution_status: str | None = None,
) -> float:
    base = {"low": 0.35, "medium": 0.6, "high": 0.85}.get(priority, 0.6)
    score = (
        0.35 * base
        + 0.2 * min(1.0, factors.hypothesis_count / 3)
        + 0.2 * factors.support_gap
        + 0.2 * factors.expected_information_gain
        + 0.05 * (1 - factors.estimated_cost)
    )
    if resolution_status == "resolved":
        score *= 0.1
    elif resolution_status == "partially_resolved":
        score *= 0.72
    if factors.human_priority_override is not None:
        score = 0.7 * score + 0.3 * factors.human_priority_override
    return round(min(max(score, 0.0), 1.0), 4)


def _estimate_uncertainty_cost(record: UncertaintyRecord) -> float:
    text = f"{record.question} {record.description}".lower()
    if any(token in text for token in ("lag", "滞后", "跨时间", "time", "stability", "稳定")):
        return 0.65
    if any(token in text for token in ("mediat", "中介", "through", "independent", "独立")):
        return 0.45
    return 0.35


def _candidate_type(record: UncertaintyRecord) -> str:
    if record.resolution_status == "partially_resolved":
        return "validation_followup"
    text = f"{record.question} {record.description}".lower()
    if any(token in text for token in ("mediat", "中介", "through")):
        return "mediator_test"
    if any(token in text for token in ("lag", "滞后", "跨时间", "stability", "稳定")):
        return "lag_sensitivity"
    if any(token in text for token in ("independent", "独立")):
        return "incremental_gain"
    return "distinguishing"


def _design_from_uncertainty(
    record: UncertaintyRecord,
    target: str,
    primary_x: str,
    control_base: list[str],
    planning_context: PlanningContext,
    node_index: dict[str, object],
) -> ExperimentDesign:
    text = f"{record.question} {record.description}".lower()
    control = _unique_preserve_order(control_base)
    treatment = _unique_preserve_order(control + [primary_x])
    lags: dict[str, list[int]] = {}
    notes = [f"generated_from:{record.uncertainty_id}"]

    if planning_context.preferred_features:
        focus_feature = planning_context.preferred_features[0]
        if planning_context.prefer_simple_design:
            treatment = [focus_feature]
            notes.append(f"human_feedback_focus_single_feature:{focus_feature}")
        elif focus_feature not in treatment:
            treatment = _unique_preserve_order(treatment + [focus_feature])
            notes.append(f"human_feedback_focus_feature:{focus_feature}")

    if any(token in text for token in ("lag", "滞后", "跨时间", "stability", "稳定")):
        lags[primary_x] = [1, 2, 3]
        notes.append("test temporal stability with lag variants")
    elif any(token in text for token in ("mediat", "中介", "through")):
        notes.append("compare mediator-enriched baseline vs primary variable treatment")
    elif any(token in text for token in ("independent", "独立")):
        notes.append("test whether primary variable adds independent predictive value")
    else:
        notes.append("generic distinguishing experiment")

    if record.resolution_status == "partially_resolved":
        notes.append("validation_followup_for_partially_resolved_disagreement")
        lags = {}
        if primary_x not in treatment:
            treatment = _unique_preserve_order(treatment + [primary_x])
        notes.append("prefer validation-oriented simpler rerun to confirm leading hypothesis")

    rationale_context = _candidate_rationale_context(record, node_index)
    if rationale_context["focus_features"]:
        notes.append(f"rationale_focus_features:{','.join(rationale_context['focus_features'])}")
    if rationale_context["source_types"]:
        notes.append(f"rationale_source_types:{','.join(rationale_context['source_types'])}")

    return ExperimentDesign(
        target=target,
        control=control,
        treatment=treatment,
        lags=lags,
        notes=notes,
    )


def _build_hypothesis_predictions(record: UncertaintyRecord, node_index: dict[str, object]) -> dict[str, HypothesisPrediction]:
    predictions: dict[str, HypothesisPrediction] = {}
    for hypothesis_id in record.related_hypotheses:
        node = node_index.get(hypothesis_id)
        if node is None:
            continue
        disagreement = record.disagreement.get(hypothesis_id) if record.disagreement else None
        expected_effect = disagreement.expected if disagreement is not None else _expected_from_node(node)
        predictions[hypothesis_id] = HypothesisPrediction(
            expected_effect=expected_effect,
            expected_range=_expected_range_from_effect(
                expected_effect=expected_effect,
                support_score=getattr(node, "support_score", 0.5),
            ),
        )
    return predictions


def _annotate_candidate_estimates(
    *,
    candidate: CandidateExperiment,
    task: ScientificTask,
    data_dictionary: DataDictionary,
    hypothesis_tree: HypothesisTreeState,
    experiment_memory: ExperimentMemoryState | None,
    current_round: int,
) -> None:
    ig, ig_rationale = _formal_information_gain(candidate, current_round=current_round)
    pg, pg_rationale = _formal_expected_performance_gain(
        candidate=candidate,
        experiment_memory=experiment_memory,
        current_round=current_round,
    )
    risk, risk_rationale = _formal_risk_score(
        candidate=candidate,
        task=task,
        data_dictionary=data_dictionary,
        hypothesis_tree=hypothesis_tree,
        experiment_memory=experiment_memory,
    )
    cost, cost_rationale = _formal_cost_score(
        candidate=candidate,
        task=task,
        data_dictionary=data_dictionary,
        hypothesis_tree=hypothesis_tree,
        experiment_memory=experiment_memory,
    )
    candidate.estimated_information_gain = EstimatedValue(value=ig, rationale=ig_rationale)
    candidate.estimated_performance_gain = EstimatedValue(value=pg, rationale=pg_rationale)
    candidate.estimated_risk = EstimatedValue(value=risk, rationale=risk_rationale)
    candidate.estimated_cost = EstimatedValue(value=cost, rationale=cost_rationale)


def _expected_range_from_effect(*, expected_effect: str, support_score: float) -> list[float]:
    confidence = min(max(support_score, 0.05), 0.95)
    width = max(0.015, 0.08 - confidence * 0.04)
    if expected_effect == "negative":
        center = -max(0.02, 0.03 + confidence * 0.05)
        return [round(center - width, 4), round(center + width, 4)]
    if expected_effect == "near_zero":
        return [round(-width, 4), round(width, 4)]
    center = max(0.02, 0.03 + confidence * 0.05)
    return [round(center - width, 4), round(center + width, 4)]


def _formal_information_gain(
    candidate: CandidateExperiment,
    *,
    current_round: int,
) -> tuple[float, str]:
    predictions = list(candidate.hypothesis_predictions.items())
    if len(predictions) < 2:
        fallback = 0.5 if candidate.tested_hypotheses else 0.18
        return (
            round(fallback, 4),
            "候选实验涉及的可区分假设不足 2 个，按文档约定退化为中性信息增益估计。"
            if candidate.tested_hypotheses
            else "baseline/校准实验主要提供基线，不承担核心假设区分任务，因此信息增益记为较低值。",
        )

    pair_scores: list[float] = []
    for index, (_, left) in enumerate(predictions):
        for _, right in predictions[index + 1 :]:
            overlap = _prediction_overlap(left.expected_range, right.expected_range)
            pair_scores.append(1.0 - overlap)
    ig = sum(pair_scores) / len(pair_scores)
    rationale = (
        "按 IG_pair(H_i,H_j)=1-overlap、IG(E)=avg(IG_pair) 计算；"
        f"本候选共比较 {len(pair_scores)} 组假设预测区间，平均区分度为 {ig:.4f}。"
    )
    if current_round > 1:
        rationale += " 当前仍用于实验前评估，待实验完成后再用后验 KL 散度做审计。"
    return round(min(max(ig, 0.0), 1.0), 4), rationale


def _prediction_overlap(left_range: list[float] | None, right_range: list[float] | None) -> float:
    if not left_range or not right_range:
        return 0.5
    left_mu = (left_range[0] + left_range[1]) / 2
    right_mu = (right_range[0] + right_range[1]) / 2
    left_sigma = max(abs(left_range[1] - left_range[0]) / 4, EPSILON)
    right_sigma = max(abs(right_range[1] - right_range[0]) / 4, EPSILON)
    lower = min(left_mu - 4 * left_sigma, right_mu - 4 * right_sigma)
    upper = max(left_mu + 4 * left_sigma, right_mu + 4 * right_sigma)
    steps = 256
    dx = (upper - lower) / steps
    overlap = 0.0
    for step in range(steps):
        x = lower + (step + 0.5) * dx
        overlap += min(_normal_pdf(x, left_mu, left_sigma), _normal_pdf(x, right_mu, right_sigma)) * dx
    return min(max(overlap, 0.0), 1.0)


def _normal_pdf(x: float, mean: float, sigma: float) -> float:
    z = (x - mean) / max(sigma, EPSILON)
    return math.exp(-0.5 * z * z) / (max(sigma, EPSILON) * math.sqrt(2 * math.pi))


def _formal_expected_performance_gain(
    *,
    candidate: CandidateExperiment,
    experiment_memory: ExperimentMemoryState | None,
    current_round: int,
) -> tuple[float, str]:
    current_best_rmse = _current_best_rmse(experiment_memory)
    if current_round <= 1 or current_best_rmse is None:
        return (
            0.0,
            "第一轮或尚无历史实验结果时，按规则将 PG_expected 置为 0，不参与综合价值计算。",
        )
    predicted_after_rmse, similarity, historical_gain = _predict_after_rmse_from_history(
        candidate=candidate,
        current_best_rmse=current_best_rmse,
        experiment_memory=experiment_memory,
    )
    pg_expected = (current_best_rmse - predicted_after_rmse) / max(current_best_rmse, EPSILON)
    rationale = (
        "按 PG_expected(E)=(RMSE_current_best-RMSE_predicted_after(E))/RMSE_current_best 计算；"
        f"当前最优 RMSE={current_best_rmse:.4f}，历史相似度={similarity:.4f}，"
        f"历史平均实际增益={historical_gain:.4f}，预测实验后 RMSE={predicted_after_rmse:.4f}。"
    )
    return round(min(max(pg_expected, 0.0), 1.0), 4), rationale


def _predict_after_rmse_from_history(
    *,
    candidate: CandidateExperiment,
    current_best_rmse: float,
    experiment_memory: ExperimentMemoryState | None,
) -> tuple[float, float, float]:
    if experiment_memory is None:
        return current_best_rmse, 0.0, 0.0

    weighted_gain = 0.0
    similarity_total = 0.0
    fallback_gains: list[float] = []
    for entry in experiment_memory.entries:
        metrics = entry.metrics_snapshot
        gain = _entry_actual_pg(metrics)
        if gain is None:
            continue
        gain = max(gain, 0.0)
        fallback_gains.append(gain)
        similarity = _historical_similarity(candidate, entry)
        if similarity <= 0.0:
            continue
        weighted_gain += similarity * gain
        similarity_total += similarity

    historical_gain = weighted_gain / similarity_total if similarity_total > 0 else (
        sum(fallback_gains) / len(fallback_gains) if fallback_gains else 0.0
    )
    design_bonus = min(0.04, 0.01 * max(len(candidate.design.treatment) - len(candidate.design.control), 0))
    lag_penalty = 0.01 * len(candidate.design.lags)
    predicted_gain = min(max(historical_gain + design_bonus - lag_penalty, 0.0), 0.35)
    predicted_after_rmse = max(current_best_rmse * (1.0 - predicted_gain), EPSILON)
    normalized_similarity = min(similarity_total / max(len(fallback_gains), 1), 1.0) if fallback_gains else 0.0
    return predicted_after_rmse, normalized_similarity, historical_gain


def _entry_actual_pg(metrics) -> float | None:
    if metrics is None:
        return None
    if metrics.pg_actual_signed is not None:
        return metrics.pg_actual_signed
    if metrics.baseline_rmse is None or metrics.treatment_rmse is None:
        return None
    return (metrics.baseline_rmse - metrics.treatment_rmse) / max(metrics.baseline_rmse, EPSILON)


def _historical_similarity(candidate: CandidateExperiment, entry) -> float:
    hypothesis_overlap = _jaccard_similarity(set(candidate.tested_hypotheses), set(entry.tested_hypotheses))
    finding_overlap = _token_overlap(candidate.purpose, " ".join(entry.key_findings))
    status_bonus = 0.1 if entry.status == "completed" else 0.0
    return min(0.65 * hypothesis_overlap + 0.25 * finding_overlap + status_bonus, 1.0)


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    return len(left & right) / max(len(left | right), 1)


def _token_overlap(left: str, right: str) -> float:
    left_tokens = {token for token in left.lower().replace("、", " ").replace(",", " ").split() if token}
    right_tokens = {token for token in right.lower().replace("、", " ").replace(",", " ").split() if token}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)


def _formal_risk_score(
    *,
    candidate: CandidateExperiment,
    task: ScientificTask,
    data_dictionary: DataDictionary,
    hypothesis_tree: HypothesisTreeState,
    experiment_memory: ExperimentMemoryState | None,
) -> tuple[float, str]:
    node_index = hypothesis_tree.node_index()
    supports = [
        node_index[hypothesis_id].support_score
        for hypothesis_id in candidate.tested_hypotheses
        if hypothesis_id in node_index
    ]
    avg_support = sum(supports) / len(supports) if supports else 0.5
    support_span = (max(supports) - min(supports)) if len(supports) >= 2 else 0.0
    d1 = min(max(1.0 - avg_support + (0.1 if support_span > 0.30 else 0.0), 0.0), 1.0)

    sample_risk = 1.0 - min(data_dictionary.total_samples / 200.0, 1.0)
    multi_source_risk = 0.5 if len(task.payload.data_sources) > 1 else 0.0
    leakage_risk = 0.5 if not task.payload.constraints.no_future_information else 0.0
    d2 = min(0.4 * sample_risk + 0.3 * multi_source_risk + 0.3 * leakage_risk, 1.0)

    control_risk = 0.6 if not candidate.design.control else (0.3 if len(candidate.design.control) < 2 else 0.0)
    reproducibility_risk = 0.2 if _has_similar_history(candidate, experiment_memory) else 0.0
    design_complexity_risk = min(0.2 * len(candidate.design.lags) + 0.1 * max(len(candidate.design.treatment) - 3, 0), 0.7)
    d3 = min(0.4 * design_complexity_risk + 0.3 * control_risk + 0.3 * reproducibility_risk, 1.0)

    budget = task.payload.constraints.resource_budget
    token_budget = budget.token_budget if budget and budget.token_budget else 200000
    time_budget = budget.max_time_seconds_per_round if budget and budget.max_time_seconds_per_round else 300
    estimated_tokens = _estimate_llm_tokens(candidate, hypothesis_tree, experiment_memory)
    compute_seconds = _estimate_compute_seconds(candidate, data_dictionary)
    compute_risk = 1.0 if estimated_tokens > token_budget * 0.8 else (0.5 if estimated_tokens > token_budget * 0.5 else 0.0)
    complexity_risk = min(compute_seconds / max(time_budget, 1), 1.0)
    human_risk = 0.5 if candidate.requires_human_review else 0.0
    d4 = min(0.4 * compute_risk + 0.35 * complexity_risk + 0.25 * human_risk, 1.0)

    risk = min(0.35 * d1 + 0.25 * d2 + 0.25 * d3 + 0.15 * d4, 1.0)
    rationale = (
        "按 Risk(E)=0.35·D1+0.25·D2+0.25·D3+0.15·D4 计算；"
        f"D1={d1:.4f}(支持度先验), D2={d2:.4f}(数据质量/对齐), "
        f"D3={d3:.4f}(设计风险), D4={d4:.4f}(资源执行风险)。"
    )
    return round(risk, 4), rationale


def _formal_cost_score(
    *,
    candidate: CandidateExperiment,
    task: ScientificTask,
    data_dictionary: DataDictionary,
    hypothesis_tree: HypothesisTreeState,
    experiment_memory: ExperimentMemoryState | None,
) -> tuple[float, str]:
    budget = task.payload.constraints.resource_budget
    token_budget = budget.token_budget if budget and budget.token_budget else 200000
    time_budget = budget.max_time_seconds_per_round if budget and budget.max_time_seconds_per_round else 300
    c1_raw = _estimate_llm_tokens(candidate, hypothesis_tree, experiment_memory)
    c1 = min(c1_raw / max(token_budget, 1), 1.0)
    c2_raw = _estimate_compute_seconds(candidate, data_dictionary)
    c2 = min(c2_raw / max(time_budget, 1), 1.0)
    c3 = 1.0 if candidate.requires_human_review else 0.0
    cost = max(0.50 * c1 + 0.35 * c2 + 0.15 * c3, 0.05)
    rationale = (
        "按 Cost(E)=max(0.50·C1+0.35·C2+0.15·C3, 0.05) 计算；"
        f"C1={c1:.4f}(token预算占比), C2={c2:.4f}(计算时间占比), C3={c3:.4f}(人工审核成本)。"
    )
    return round(min(cost, 1.0), 4), rationale


def _estimate_llm_tokens(
    candidate: CandidateExperiment,
    hypothesis_tree: HypothesisTreeState,
    experiment_memory: ExperimentMemoryState | None,
) -> float:
    active_hypotheses = [node for node in hypothesis_tree.nodes if node.status in {"active", "converged"}]
    input_tokens = 2000 + len(str(candidate.design.model_dump(mode="json"))) / 3
    input_tokens += sum((len(node.statement) / 3) + 200 for node in active_hypotheses)
    history_count = len(experiment_memory.entries[-3:]) if experiment_memory else 0
    input_tokens += 300 * history_count
    output_tokens = 1500
    return input_tokens + output_tokens


def _estimate_compute_seconds(candidate: CandidateExperiment, data_dictionary: DataDictionary) -> float:
    n_samples = max(data_dictionary.total_samples, 1)
    n_features = max(len(set(candidate.design.control + candidate.design.treatment)), 1)
    step_count = max(len(candidate.design.lags), 1)
    data_coeff = max(1.0, (n_samples / 1000.0) * (n_features / 20.0))
    step_coeff = 1.0 + (step_count - 1) * 0.2
    return 10.0 * data_coeff * step_coeff


def _has_similar_history(candidate: CandidateExperiment, experiment_memory: ExperimentMemoryState | None) -> bool:
    if experiment_memory is None:
        return False
    return any(_historical_similarity(candidate, entry) >= 0.6 for entry in experiment_memory.entries)


def _estimate_performance_gain(
    record: UncertaintyRecord,
    primary_x: str,
    experiment_memory: ExperimentMemoryState | None = None,
) -> float:
    return _estimate_performance_gain_from_text(
        text=f"{record.question} {record.description}",
        primary_x=primary_x,
        experiment_memory=experiment_memory,
        partially_resolved=record.resolution_status == "partially_resolved",
    )


def _estimate_performance_gain_from_text(
    *,
    text: str,
    primary_x: str,
    experiment_memory: ExperimentMemoryState | None = None,
    partially_resolved: bool = False,
) -> float:
    current_best_rmse = _current_best_rmse(experiment_memory)
    if current_best_rmse is None:
        return 0.0
    predicted_after_rmse = _predict_after_rmse(
        text=text,
        primary_x=primary_x,
        current_best_rmse=current_best_rmse,
        experiment_memory=experiment_memory,
        partially_resolved=partially_resolved,
    )
    pg_expected = (current_best_rmse - predicted_after_rmse) / max(current_best_rmse, EPSILON)
    return round(min(max(pg_expected, 0.0), 1.0), 4)


def _performance_gain_rationale(
    record: UncertaintyRecord,
    primary_x: str,
    experiment_memory: ExperimentMemoryState | None = None,
) -> str:
    return _performance_gain_rationale_from_text(
        text=f"{record.question} {record.description}",
        primary_x=primary_x,
        experiment_memory=experiment_memory,
        partially_resolved=record.resolution_status == "partially_resolved",
    )


def _performance_gain_rationale_from_text(
    *,
    text: str,
    primary_x: str,
    experiment_memory: ExperimentMemoryState | None = None,
    partially_resolved: bool = False,
) -> str:
    current_best_rmse = _current_best_rmse(experiment_memory)
    if current_best_rmse is None:
        return "当前无历史实验 RMSE 可供校准，第一轮或无历史时将 PG_expected 视为 0。"
    predicted_after_rmse = _predict_after_rmse(
        text=text,
        primary_x=primary_x,
        current_best_rmse=current_best_rmse,
        experiment_memory=experiment_memory,
        partially_resolved=partially_resolved,
    )
    pg_expected = (current_best_rmse - predicted_after_rmse) / max(current_best_rmse, EPSILON)
    return (
        "按 PG_expected(E) = (RMSE_current_best - RMSE_predicted_after(E)) / RMSE_current_best 估计；"
        f"当前最优 RMSE={current_best_rmse:.4f}，预测实验后 RMSE={predicted_after_rmse:.4f}，"
        f"得到 PG_expected≈{max(pg_expected, 0.0):.4f}。"
    )


def _predict_after_rmse(
    *,
    text: str,
    primary_x: str,
    current_best_rmse: float,
    experiment_memory: ExperimentMemoryState | None = None,
    partially_resolved: bool = False,
) -> float:
    text = text.lower()
    estimated_gain = _historical_pg_mean(experiment_memory)
    if primary_x.lower() in text:
        estimated_gain += 0.025
    if any(token in text for token in ("independent", "独立", "incremental", "增量")):
        estimated_gain += 0.035
    if any(token in text for token in ("lag", "滞后", "稳定", "跨时间")):
        estimated_gain += 0.02
    if any(token in text for token in ("mediat", "中介", "through")):
        estimated_gain += 0.015
    if partially_resolved:
        estimated_gain = max(estimated_gain - 0.015, 0.0)
    estimated_gain = min(max(estimated_gain, 0.0), 0.25)
    return max(current_best_rmse * (1.0 - estimated_gain), EPSILON)


def _estimate_baseline_performance_gain(experiment_memory: ExperimentMemoryState | None = None) -> float:
    current_best_rmse = _current_best_rmse(experiment_memory)
    if current_best_rmse is None:
        return 0.0
    predicted_after_rmse = current_best_rmse
    return round((current_best_rmse - predicted_after_rmse) / max(current_best_rmse, EPSILON), 4)


def _baseline_performance_gain_rationale(experiment_memory: ExperimentMemoryState | None = None) -> str:
    current_best_rmse = _current_best_rmse(experiment_memory)
    if current_best_rmse is None:
        return "当前无历史实验 RMSE 可供校准，baseline benchmark 的 PG_expected 记为 0。"
    return (
        "按 PG_expected(E) = (RMSE_current_best - RMSE_predicted_after(E)) / RMSE_current_best 估计；"
        f"baseline benchmark 预期保持当前最优 RMSE={current_best_rmse:.4f}，因此 PG_expected≈0.0000。"
    )


def _current_best_rmse(experiment_memory: ExperimentMemoryState | None) -> float | None:
    if experiment_memory is None:
        return None
    best: float | None = None
    for entry in experiment_memory.entries:
        metrics = entry.metrics_snapshot
        if metrics is None:
            continue
        for value in (metrics.baseline_rmse, metrics.treatment_rmse):
            if value is None:
                continue
            best = value if best is None else min(best, value)
    return best


def _historical_pg_mean(experiment_memory: ExperimentMemoryState | None) -> float:
    if experiment_memory is None:
        return 0.0
    values: list[float] = []
    for entry in experiment_memory.entries:
        metrics = entry.metrics_snapshot
        if metrics is None or metrics.baseline_rmse is None or metrics.treatment_rmse is None:
            continue
        before = metrics.baseline_rmse
        after = metrics.treatment_rmse
        gain = (before - after) / max(before, EPSILON)
        values.append(gain)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _estimate_candidate_risk(record: UncertaintyRecord) -> float:
    if record.resolution_status == "partially_resolved":
        return 0.28
    text = f"{record.question} {record.description}".lower()
    if any(token in text for token in ("lag", "滞后", "跨时间")):
        return 0.6
    if any(token in text for token in ("mediat", "中介")):
        return 0.5
    return 0.35


def _estimate_candidate_cost(record: UncertaintyRecord) -> float:
    if record.resolution_status == "partially_resolved":
        return 0.25
    return _estimate_uncertainty_cost(record)


def _unique_preserve_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _collect_hypothesis_ids(
    top_uncertainties: list[PrioritizedUncertainty],
    uncertainty_state: UncertaintyState,
) -> list[str]:
    ids: list[str] = []
    record_index = uncertainty_state.record_index()
    for item in top_uncertainties:
        record = record_index.get(item.uncertainty_id)
        if record is None:
            continue
        ids.extend(record.related_hypotheses)
    return _unique_preserve_order(ids)


def _build_planning_context(
    planning_feedback: str | None,
    data_dictionary: DataDictionary,
) -> PlanningContext:
    if not planning_feedback:
        return PlanningContext()

    text = planning_feedback.lower()
    preferred_features = tuple(
        feature for feature in data_dictionary.feature_candidates if feature.lower() in text
    )
    keywords = tuple(
        keyword
        for keyword in ("单变量", "独立", "中介", "滞后", "稳定", "baseline", "incremental")
        if keyword.lower() in text
    )
    prefer_simple_design = any(token in text for token in ("单变量", "single", "只测", "先测试"))
    return PlanningContext(
        guidance_text=planning_feedback,
        preferred_features=preferred_features,
        preferred_keywords=keywords,
        prefer_simple_design=prefer_simple_design,
    )


def _rank_uncertainties_with_feedback(
    top_uncertainties: list[PrioritizedUncertainty],
    uncertainty_state: UncertaintyState,
    planning_context: PlanningContext,
) -> list[PrioritizedUncertainty]:
    if not planning_context.guidance_text:
        return top_uncertainties

    record_index = uncertainty_state.record_index()

    def score(item: PrioritizedUncertainty) -> tuple[float, float]:
        record = record_index.get(item.uncertainty_id)
        if record is None:
            return (item.priority_score, item.priority_score)
        boost = 0.0
        source = f"{record.question} {record.description}".lower()
        for feature in planning_context.preferred_features:
            if feature.lower() in source:
                boost += 0.2
        for keyword in planning_context.preferred_keywords:
            if keyword.lower() in source:
                boost += 0.1
        return (round(item.priority_score + boost, 4), item.priority_score)

    return sorted(top_uncertainties, key=score, reverse=True)


def _planning_notes(planning_context: PlanningContext) -> list[str]:
    if not planning_context.guidance_text:
        return []
    notes = [f"human_feedback:{planning_context.guidance_text}"]
    if planning_context.preferred_features:
        notes.append(f"preferred_features:{','.join(planning_context.preferred_features)}")
    if planning_context.prefer_simple_design:
        notes.append("preferred_design:simple")
    return notes


def _build_candidate_novelty(planning_context: PlanningContext) -> str:
    if planning_context.guidance_text:
        return "new uncertainty-focused experiment with human feedback guidance"
    return "new uncertainty-focused experiment"


def _candidate_set_note(candidate_count: int, planning_context: PlanningContext) -> str | None:
    notes: list[str] = []
    if candidate_count < 3:
        notes.append("当前候选实验不足3个，建议后续由实验规划者补充更多候选实验。")
    if planning_context.guidance_text:
        notes.append(f"本轮候选已纳入 human_feedback: {planning_context.guidance_text}")
    return " ".join(notes) if notes else None


def _expected_from_node(node) -> str:
    if node.status in {"weakened", "pruned"} or node.support_score < 0.40:
        return "near_zero"
    if any(token in node.statement.lower() for token in ("伴随", "competition", "null")):
        return "near_zero"
    return "positive"


def _candidate_rationale_context(record: UncertaintyRecord, node_index: dict[str, object]) -> dict[str, list[str] | str]:
    source_types: list[str] = []
    focus_features: list[str] = []
    trigger_tags: list[str] = []
    summaries: list[str] = []
    for hypothesis_id in record.related_hypotheses:
        node = node_index.get(hypothesis_id)
        if node is None or node.generation_rationale is None:
            continue
        rationale = node.generation_rationale
        trigger_tags.append(rationale.trigger)
        summaries.append(f"{hypothesis_id}:{rationale.summary}")
        focus_features.extend(rationale.derived_features)
        source_types.extend(signal.signal_type for signal in rationale.source_signals)
    return {
        "trigger_tags": _unique_preserve_order(trigger_tags),
        "focus_features": _unique_preserve_order(focus_features),
        "source_types": _unique_preserve_order(source_types),
        "summary": " | ".join(summaries[:3]),
    }


def _candidate_source_context(
    record: UncertaintyRecord,
    node_index: dict[str, object],
) -> dict[str, object]:
    context: dict[str, object] = {}
    for hypothesis_id in record.related_hypotheses:
        node = node_index.get(hypothesis_id)
        if node is None or node.generation_rationale is None:
            continue
        context[hypothesis_id] = node.generation_rationale.model_copy(deep=True)
    return context


def _candidate_purpose(record: UncertaintyRecord, rationale_context: dict[str, list[str] | str]) -> str:
    triggers = rationale_context["trigger_tags"]
    if triggers:
        return f"resolve {record.uncertainty_id}: {record.question}，并区分触发源 {','.join(triggers[:2])}"
    return f"resolve {record.uncertainty_id}: {record.question}"


def _distinguishing_insight(
    record: UncertaintyRecord,
    rationale_context: dict[str, list[str] | str],
    primary_x: str,
) -> str:
    if rationale_context["summary"]:
        return (
            f"通过比较 baseline 与 treatment，判断 {primary_x} 是否能减少与 {record.question} 相关的不确定性；"
            f"本实验重点区分这些假设来源: {rationale_context['summary']}。"
        )
    return f"通过比较 baseline 与 treatment，判断 {primary_x} 是否能减少与 {record.question} 相关的不确定性。"


def _information_gain_rationale(
    record: UncertaintyRecord,
    rationale_context: dict[str, list[str] | str],
) -> str:
    if rationale_context["trigger_tags"]:
        return (
            "优先级越高，说明该实验更可能消除关键科学不确定性；"
            f"同时可区分由 {','.join(rationale_context['trigger_tags'][:2])} 触发的假设来源。"
        )
    return "优先级越高，说明该实验更可能消除关键科学不确定性。"


def _rationale_design_notes(
    record: UncertaintyRecord,
    rationale_context: dict[str, list[str] | str],
) -> list[str]:
    notes: list[str] = []
    if rationale_context["trigger_tags"]:
        notes.append(f"hypothesis_triggers:{','.join(rationale_context['trigger_tags'])}")
    if rationale_context["summary"]:
        notes.append(f"hypothesis_source_summary:{rationale_context['summary']}")
    if record.disagreement:
        notes.append(f"disagreement_hypotheses:{','.join(record.disagreement.keys())}")
    return notes
