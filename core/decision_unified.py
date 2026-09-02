from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
                estimated_information_gain=EstimatedValue(value=0.2, rationale="baseline mainly serves calibration"),
                estimated_performance_gain=EstimatedValue(
                    value=_estimate_baseline_performance_gain(experiment_memory),
                    rationale=_baseline_performance_gain_rationale(experiment_memory),
                ),
                estimated_risk=EstimatedValue(value=0.15, rationale="baseline benchmark risk is low"),
                estimated_cost=EstimatedValue(value=0.15, rationale="baseline benchmark is cheap"),
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
            candidates.append(candidate)

        if len(candidates) < 3:
            candidates.append(
                CandidateExperiment(
                    experiment_id=f"E_R{uncertainty_state.current_round + 1:02d}_S1",
                    type="sensitivity_probe",
                    purpose=f"test lag sensitivity of {primary_x}",
                    scientific_question=f"{primary_x} 的时间滞后设定是否影响实验结论稳定性？",
                    tested_hypotheses=_collect_hypothesis_ids(top_uncertainties, uncertainty_state),
                    design=ExperimentDesign(
                        target=target,
                        control=control_base,
                        treatment=_unique_preserve_order(control_base + [primary_x]),
                        lags={primary_x: [1, 2, 3]},
                        notes=["fallback sensitivity probe to ensure candidate diversity"],
                    ),
                    estimated_information_gain=EstimatedValue(value=0.55, rationale="sensitivity probe can reveal temporal robustness"),
                    estimated_performance_gain=EstimatedValue(
                        value=_estimate_performance_gain_from_text(
                            text=f"{primary_x} lag sensitivity temporal robustness",
                            primary_x=primary_x,
                            experiment_memory=experiment_memory,
                        ),
                        rationale=_performance_gain_rationale_from_text(
                            text=f"{primary_x} lag sensitivity temporal robustness",
                            primary_x=primary_x,
                            experiment_memory=experiment_memory,
                        ),
                    ),
                    estimated_risk=EstimatedValue(value=0.45, rationale="multiple lag settings increase design uncertainty"),
                    estimated_cost=EstimatedValue(value=0.35, rationale="additional lag variants add moderate cost"),
                    requires_human_review=True,
                    novelty="fallback candidate to satisfy minimum diversity",
                )
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
        predictions[hypothesis_id] = HypothesisPrediction(
            expected_effect=(disagreement.expected if disagreement is not None else _expected_from_node(node)),
        )
    return predictions


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
