from __future__ import annotations

from datetime import datetime
from typing import Any

from core.state_repository import UnifiedStateRepository
from core.support_update_rules import compute_support_update_from_reasoning, priority_after_action
from core.unified_schema import (
    CritiqueRecord,
    EvidenceItem,
    EvaluationResult,
    ExperimentMemoryEntry,
    ExperimentMemoryState,
    ExperimentProtocol,
    ExperimentResult,
    HypothesisTreeState,
    InterpretationEnhancement,
    LatestTreeUpdate,
    ProcessPhase,
    ProcessState,
    PrioritizedUncertainty,
    ProcessStep,
    ReasoningTraceEntry,
    SupportHistoryEntry,
    TreeSummary,
    UncertaintyHistoryEntry,
    UncertaintyPriorityQueue,
    UncertaintyRecord,
    UncertaintyState,
)


class UnifiedStateUpdater:
    """Apply execution and evaluation outputs back into the persistent knowledge state."""

    def __init__(self, repository: UnifiedStateRepository) -> None:
        self.repository = repository

    def apply_evaluation(
        self,
        *,
        protocol: ExperimentProtocol,
        result: ExperimentResult,
        evaluation: EvaluationResult,
        interpretation_enhancements: list[InterpretationEnhancement] | None = None,
        interpreter_source: str = "scientific_interpreter_llm",
        protocol_path: str | None = "config/latest_protocol.json",
        result_path: str | None = None,
        evaluation_path: str | None = None,
    ) -> dict[str, object]:
        tree = self.repository.load_hypothesis_tree()
        uncertainties = self.repository.load_uncertainties()
        experiment_memory = self.repository.load_experiment_memory()
        process_state = self.repository.load_process_state()

        tree = self._update_hypothesis_tree(tree, protocol, evaluation)
        uncertainties = self._update_uncertainties(uncertainties, protocol, evaluation)
        experiment_memory = self._update_experiment_memory(
            experiment_memory,
            protocol=protocol,
            result=result,
            evaluation=evaluation,
            protocol_path=protocol_path,
            result_path=result_path,
            evaluation_path=evaluation_path,
        )
        if interpretation_enhancements:
            tree, uncertainties, experiment_memory = self._apply_interpretation_enhancements(
                tree=tree,
                uncertainties=uncertainties,
                experiment_memory=experiment_memory,
                protocol=protocol,
                interpretation_enhancements=interpretation_enhancements,
                interpreter_source=interpreter_source,
            )
        process_state = self._update_process_state(process_state, protocol.round_id)

        self.repository.save_hypothesis_tree(tree)
        self.repository.save_uncertainties(uncertainties)
        self.repository.save_experiment_memory(experiment_memory)
        self.repository.save_process_state(process_state)

        return {
            "hypothesis_tree": tree,
            "uncertainties": uncertainties,
            "experiment_memory": experiment_memory,
            "process_state": process_state,
        }

    def _apply_interpretation_enhancements(
        self,
        *,
        tree: HypothesisTreeState,
        uncertainties: UncertaintyState,
        experiment_memory: ExperimentMemoryState,
        protocol: ExperimentProtocol,
        interpretation_enhancements: list[InterpretationEnhancement],
        interpreter_source: str,
    ) -> tuple[HypothesisTreeState, UncertaintyState, ExperimentMemoryState]:
        node_index = tree.node_index()
        uncertainty_index = uncertainties.record_index()
        memory_entry = experiment_memory.entry_index().get(protocol.experiment_id)
        now = datetime.now()

        for enhancement in interpretation_enhancements:
            support_outcome = compute_support_update_from_reasoning(
                current_support=node_index.get(enhancement.target_hypothesis_id).support_score
                if enhancement.target_hypothesis_id and enhancement.target_hypothesis_id in node_index
                else 0.5,
                impact_direction=enhancement.impact_direction,
                impact_strength=enhancement.impact_strength,
                confidence=enhancement.confidence,
            )
            if enhancement.target_hypothesis_id:
                node = node_index.get(enhancement.target_hypothesis_id)
                if node is not None:
                    node.support_score = support_outcome.support_after
                    node.status = support_outcome.status
                    node.updated_at_round = protocol.round_id
                    node.support_history.append(
                        SupportHistoryEntry(
                            round=protocol.round_id,
                            score=support_outcome.support_after,
                            event=f"scientific_interpreter:{enhancement.enhancement_id}",
                        )
                    )
                    node.evidence_items.append(
                        EvidenceItem(
                            id=enhancement.enhancement_id,
                            type="expert_judgment",
                            description=enhancement.interpretation,
                            source=interpreter_source,
                            added_at_round=protocol.round_id,
                            support_weight=min(max(abs(support_outcome.support_delta), 0.03), 0.2),
                        )
                    )
                    node.critiques.append(
                        CritiqueRecord(
                            id=f"{enhancement.enhancement_id}_critique",
                            content=enhancement.interpretation,
                            from_role="scientific_interpreter",
                            added_at_round=protocol.round_id,
                        )
                    )
                    if enhancement.suggested_state_note:
                        node.alternative_explanations.append(enhancement.suggested_state_note)

            total_priority_delta = 0.0
            for uncertainty_id in enhancement.related_uncertainties:
                record = uncertainty_index.get(uncertainty_id)
                if record is None:
                    continue
                before_priority = record.priority
                record.priority = priority_after_action(
                    record.priority,
                    enhancement.uncertainty_priority_action,
                )
                record.notes = (
                    f"{record.notes} | {enhancement.interpretation}"
                    if record.notes and enhancement.interpretation not in record.notes
                    else (record.notes or enhancement.interpretation)
                )
                record.history.append(
                    UncertaintyHistoryEntry(
                        round=protocol.round_id,
                        event="scientific_interpreter",
                        source=interpreter_source,
                        description=enhancement.interpretation,
                    )
                )
                total_priority_delta += _priority_to_score(record.priority) - _priority_to_score(before_priority)

            if memory_entry is not None:
                memory_entry.reasoning_traces.append(
                    ReasoningTraceEntry(
                        trace_id=enhancement.enhancement_id,
                        round_id=protocol.round_id,
                        source=interpreter_source,
                        stage="scientific_interpreter",
                        summary=enhancement.interpretation,
                        related_hypotheses=[enhancement.target_hypothesis_id] if enhancement.target_hypothesis_id else [],
                        related_uncertainties=enhancement.related_uncertainties,
                        support_delta=support_outcome.support_delta if enhancement.target_hypothesis_id else None,
                        priority_delta=round(total_priority_delta, 4) if enhancement.related_uncertainties else None,
                    )
                )
                memory_entry.updated_at = now

        _propagate_tree_state(
            tree=tree,
            round_id=protocol.round_id,
            min_active_hypotheses=_minimum_active_hypotheses(protocol),
        )
        tree.active_hypotheses = [
            node.hypothesis_id for node in tree.nodes if node.status in {"active", "converged"}
        ]
        tree.pruned_hypotheses = [node.hypothesis_id for node in tree.nodes if node.status == "pruned"]
        tree.pending_hypotheses = [
            node.hypothesis_id for node in tree.nodes if node.status in {"draft", "pending"}
        ]
        tree.tree_summary = _rebuild_tree_summary(tree)
        tree.latest_update = LatestTreeUpdate(
            round=protocol.round_id,
            event="scientific_interpreter_applied",
            description=f"scientific interpreter applied {len(interpretation_enhancements)} interpretation enhancements",
        )
        uncertainties.last_updated = now
        uncertainties.priority_queue = UncertaintyPriorityQueue(
            last_updated=now,
            current_round=protocol.round_id,
            queue=sorted(
                [
                    PrioritizedUncertainty(
                        uncertainty_id=record.uncertainty_id,
                        question=record.question,
                        priority_score=_priority_to_score(record.priority),
                        status=record.status,
                        estimated_resolution_round=record.created_at_round + 1,
                    )
                    for record in uncertainties.records
                    if record.status not in {"resolved", "deprecated"}
                ],
                key=lambda item: item.priority_score,
                reverse=True,
            ),
            resolved=[record.uncertainty_id for record in uncertainties.records if record.status == "resolved"],
            deprecated=[record.uncertainty_id for record in uncertainties.records if record.status == "deprecated"],
        )
        if memory_entry is not None and interpretation_enhancements[0].interpretation not in memory_entry.key_findings:
            memory_entry.key_findings.append(interpretation_enhancements[0].interpretation)
        return tree, uncertainties, experiment_memory

    def _update_hypothesis_tree(
        self,
        tree: HypothesisTreeState,
        protocol: ExperimentProtocol,
        evaluation: EvaluationResult,
    ) -> HypothesisTreeState:
        node_index = tree.node_index()
        assessment_index = {
            item.hypothesis_id: item for item in evaluation.scientific.hypothesis_assessments
        }
        updated_nodes = 0
        skipped_hypotheses: list[str] = []
        signal = _classify_support_signal(evaluation)

        for hypothesis_id in protocol.tested_hypotheses:
            node = node_index.get(hypothesis_id)
            if node is None:
                skipped_hypotheses.append(hypothesis_id)
                continue

            before = node.support_score
            assessment = assessment_index.get(hypothesis_id)
            if assessment is not None:
                after = _support_after_from_assessment(
                    before=before,
                    assessment=assessment,
                    prediction=protocol.hypothesis_predictions.get(hypothesis_id),
                    observed_delta=_observed_delta_from_evaluation(evaluation),
                )
                reason = assessment.reason
            else:
                after = _apply_support_shift(before, signal)
                reason = "基于最小可运行评价回写，按实验结果信号对支持度做保守更新。"

            node.support_score = after
            node.status = _tree_status_after_update(before, after, signal, node.status)
            node.updated_at_round = protocol.round_id
            node.support_history.append(
                SupportHistoryEntry(
                    round=protocol.round_id,
                    score=after,
                    event=f"evaluation_writeback:{protocol.experiment_id}",
                )
            )
            node.evidence_items.append(
                EvidenceItem(
                    id=f"{protocol.experiment_id}_{hypothesis_id}",
                    type="experimental_result",
                    description=reason,
                    source=protocol.experiment_id,
                    added_at_round=protocol.round_id,
                    support_weight=min(max(abs(after - before), 0.05), 1.0),
                )
            )
            updated_nodes += 1

        min_active = _minimum_active_hypotheses(protocol)
        _propagate_tree_state(
            tree=tree,
            round_id=protocol.round_id,
            min_active_hypotheses=min_active,
        )
        tree.current_round = max(tree.current_round, protocol.round_id)
        tree.active_hypotheses = [
            node.hypothesis_id for node in tree.nodes if node.status in {"active", "converged"}
        ]
        tree.pruned_hypotheses = [node.hypothesis_id for node in tree.nodes if node.status == "pruned"]
        tree.pending_hypotheses = [
            node.hypothesis_id for node in tree.nodes if node.status in {"draft", "pending"}
        ]
        tree.tree_summary = _rebuild_tree_summary(tree)
        description = f"updated {updated_nodes} hypotheses from {protocol.experiment_id}"
        if skipped_hypotheses:
            description += f"; skipped missing ids {skipped_hypotheses}"
        tree.latest_update = LatestTreeUpdate(
            round=protocol.round_id,
            event="evaluation_writeback",
            description=description,
        )
        return tree

    def _update_uncertainties(
        self,
        state: UncertaintyState,
        protocol: ExperimentProtocol,
        evaluation: EvaluationResult,
    ) -> UncertaintyState:
        now = datetime.now()
        record_index = state.record_index()
        remaining = evaluation.scientific.evidence_summary.remaining_uncertainties
        disagreement_index = {
            item.uncertainty_id: item for item in evaluation.scientific.disagreement_updates
        }

        for uncertainty_id in protocol.target_uncertainties:
            record = record_index.get(uncertainty_id)
            update = disagreement_index.get(uncertainty_id)
            if record is None or update is None:
                continue
            for hypothesis_id, disagreement in record.disagreement.items():
                if hypothesis_id in update.compared_hypotheses:
                    assessment = next(
                        (item for item in evaluation.scientific.hypothesis_assessments if item.hypothesis_id == hypothesis_id),
                        None,
                    )
                    if assessment is not None and hasattr(disagreement, "support_score"):
                        disagreement.support_score = assessment.support_after
                        disagreement.status = assessment.status
            record.status = "resolved" if update.resolution_status == "resolved" else "active"
            record.resolution_status = update.resolution_status
            record.resolved_at_round = protocol.round_id if update.resolution_status == "resolved" else None
            record.resolved_by = protocol.experiment_id if update.resolution_status == "resolved" else None
            record.resolution = update.summary if update.resolution_status == "resolved" else None
            record.resolving_experiment = protocol.experiment_id
            record.notes = update.summary
            record.history.append(
                UncertaintyHistoryEntry(
                    round=protocol.round_id,
                    event="disagreement_evaluation",
                    source=protocol.experiment_id,
                    description=update.summary,
                )
            )
            if update.resolution_status == "resolved":
                continue
            if update.resolution_status == "partially_resolved":
                record.priority = "medium" if record.priority == "high" else record.priority

        for offset, item in enumerate(remaining, start=1):
            normalized = _normalize_uncertainty_item(item, protocol.round_id, offset)
            record = record_index.get(normalized["uncertainty_id"])
            if record is None:
                record = UncertaintyRecord(
                    uncertainty_id=normalized["uncertainty_id"],
                    question=normalized["question"],
                    description=normalized["description"],
                    related_hypotheses=protocol.tested_hypotheses,
                    status="active",
                    priority=normalized["priority"],
                    created_at_round=protocol.round_id,
                    created_by="state_updater",
                    notes="auto-created from evaluation remaining_uncertainties",
                )
                state.records.append(record)
                record_index[record.uncertainty_id] = record

            record.question = normalized["question"]
            record.description = normalized["description"]
            record.priority = normalized["priority"]
            record.status = "active"
            record.resolving_experiment = protocol.experiment_id
            record.history.append(
                UncertaintyHistoryEntry(
                    round=protocol.round_id,
                    event="evaluation_writeback",
                    source=protocol.experiment_id,
                    description="remaining uncertainty retained after experiment evaluation",
                )
            )

        queue_items = []
        for record in state.records:
            if record.status in {"resolved", "deprecated"}:
                continue
            queue_items.append(
                PrioritizedUncertainty(
                    uncertainty_id=record.uncertainty_id,
                    question=record.question,
                    priority_score=_priority_to_score(record.priority),
                    status=record.status,
                    estimated_resolution_round=record.created_at_round + 1,
                )
            )

        state.current_round = max(state.current_round, protocol.round_id)
        state.last_updated = now
        state.priority_queue = UncertaintyPriorityQueue(
            last_updated=now,
            current_round=protocol.round_id,
            queue=sorted(queue_items, key=lambda item: item.priority_score, reverse=True),
            resolved=[record.uncertainty_id for record in state.records if record.status == "resolved"],
            deprecated=[record.uncertainty_id for record in state.records if record.status == "deprecated"],
        )
        return state

    def _update_experiment_memory(
        self,
        memory: ExperimentMemoryState,
        *,
        protocol: ExperimentProtocol,
        result: ExperimentResult,
        evaluation: EvaluationResult,
        protocol_path: str | None,
        result_path: str | None,
        evaluation_path: str | None,
    ):
        now = datetime.now()
        entry_index = memory.entry_index()
        key_findings = [
            item.claim for item in evaluation.scientific.evidence_summary.new_evidence_for
        ] + [
            item.claim for item in evaluation.scientific.evidence_summary.new_evidence_against
        ]

        entry = entry_index.get(protocol.experiment_id)
        if entry is None:
            entry = ExperimentMemoryEntry(
                experiment_id=protocol.experiment_id,
                round_id=protocol.round_id,
                status=result.status,
                tested_hypotheses=protocol.tested_hypotheses,
                protocol_path=self.repository.relativize(protocol_path),
                result_path=self.repository.relativize(result_path),
                evaluation_path=self.repository.relativize(evaluation_path),
                metrics_snapshot=evaluation.metrics,
                key_findings=key_findings,
                visualizations=[item.path for item in evaluation.visualizations],
                created_at=now,
                updated_at=now,
            )
            memory.entries.append(entry)
        else:
            entry.round_id = protocol.round_id
            entry.status = result.status
            entry.tested_hypotheses = protocol.tested_hypotheses
            entry.protocol_path = self.repository.relativize(protocol_path)
            entry.result_path = self.repository.relativize(result_path)
            entry.evaluation_path = self.repository.relativize(evaluation_path)
            entry.metrics_snapshot = evaluation.metrics
            entry.key_findings = key_findings
            entry.visualizations = [item.path for item in evaluation.visualizations]
            entry.updated_at = now

        memory.current_round = max(memory.current_round, protocol.round_id)
        memory.last_updated = now
        return memory

    def _update_process_state(self, process_state: ProcessState, round_id: int) -> ProcessState:
        process_state.current_round = max(process_state.current_round, round_id)
        process_state.current_stage = "knowledge_memory_updated"
        process_state.current_phase = "decision_making"
        process_state.current_step = "round_review"
        process_state.progress_percentage = 75
        process_state.steps["execution"] = ProcessStep(name="execution", status="completed")
        process_state.steps["evaluation"] = ProcessStep(name="evaluation", status="completed")
        process_state.steps["state_writeback"] = ProcessStep(name="state_writeback", status="completed")
        process_state.phases["experiment_execution"] = ProcessPhase(status="completed")
        process_state.phases["result_analysis"] = ProcessPhase(status="completed")
        process_state.phases["decision_making"] = ProcessPhase(
            status="pending",
            steps={
                "round_review": ProcessStep(
                    name="round_review",
                    status="pending",
                    requires_user_approval=True,
                )
            },
        )
        return process_state


def _normalize_uncertainty_item(item: dict[str, Any], round_id: int, offset: int) -> dict[str, Any]:
    question = item.get("question") or item.get("description") or f"round_{round_id}_uncertainty_{offset}"
    return {
        "uncertainty_id": item.get("uncertainty_id") or item.get("id") or f"U_R{round_id:02d}_{offset:02d}",
        "question": question,
        "description": item.get("description") or question,
        "priority": item.get("priority", "medium"),
    }


def _priority_to_score(priority: str) -> float:
    mapping = {"low": 0.3, "medium": 0.6, "high": 0.9}
    return mapping.get(priority, 0.6)


def _classify_support_signal(evaluation: EvaluationResult) -> str:
    delta = evaluation.metrics.delta
    rmse_delta = delta.rmse
    pearson_delta = delta.pearson_r
    if rmse_delta is not None and rmse_delta < 0 and pearson_delta is not None and pearson_delta > 0:
        return "supports"
    if rmse_delta is not None and rmse_delta > 0 and pearson_delta is not None and pearson_delta < 0:
        return "weakens"
    return "mixed"


def _apply_support_shift(current_score: float, signal: str) -> float:
    shift = {"supports": 0.08, "weakens": -0.08, "mixed": 0.02}.get(signal, 0.0)
    return round(min(max(current_score + shift, 0.0), 1.0), 4)


def _status_from_signal(signal: str) -> str:
    mapping = {"supports": "supported", "weakens": "weakened", "mixed": "partially_supported"}
    return mapping.get(signal, "pending")


def _tree_status_after_update(before: float, after: float, signal: str, previous_status: str) -> str:
    if after < 0.20:
        return "pruned"
    if after >= 0.70 and previous_status in {"active", "converged"} and abs(after - before) < 0.05:
        return "converged"
    if after < 0.40 and after < before:
        return "observing"
    if previous_status == "pending" and after >= 0.40:
        return "active"
    if signal == "supports":
        return "active"
    if signal == "mixed":
        return "active" if after >= 0.40 else "observing"
    return "active" if after >= 0.40 else "observing"


def _rebuild_tree_summary(tree: HypothesisTreeState) -> TreeSummary:
    return TreeSummary(
        total_nodes=len(tree.nodes),
        active_count=sum(1 for node in tree.nodes if node.status in {"active", "converged"}),
        pruned_count=sum(1 for node in tree.nodes if node.status == "pruned"),
        pending_count=sum(1 for node in tree.nodes if node.status in {"draft", "pending"}),
    )


def _minimum_active_hypotheses(protocol: ExperimentProtocol) -> int:
    if protocol.budget and protocol.budget.max_candidates:
        return max(1, protocol.budget.max_candidates)
    return 3


def _propagate_tree_state(
    *,
    tree: HypothesisTreeState,
    round_id: int,
    min_active_hypotheses: int,
) -> None:
    node_index = tree.node_index()
    active_like = {"active", "converged"}

    for node in tree.nodes:
        if node.status != "pruned" or not node.children_ids:
            continue
        for child_id in node.children_ids:
            child = node_index.get(child_id)
            if child is None or child.status == "pruned":
                continue
            child.status = "pruned"
            child.pruned_at_round = round_id
            child.prune_reason = "父假设剪枝，继承剪枝"
            child.updated_at_round = round_id

    active_count = sum(1 for node in tree.nodes if node.status in active_like)
    activation_threshold = 0.35 if active_count < min_active_hypotheses else 0.40

    changed = True
    while changed:
        changed = False
        active_count = sum(1 for node in tree.nodes if node.status in active_like)
        activation_threshold = 0.35 if active_count < min_active_hypotheses else 0.40

        for node in tree.nodes:
            if node.parent_id is None:
                continue
            parent = node_index.get(node.parent_id)
            if parent is None:
                continue
            if parent.status == "pruned" and node.status != "pruned":
                node.status = "pruned"
                node.pruned_at_round = round_id
                node.prune_reason = "父假设剪枝，继承剪枝"
                node.updated_at_round = round_id
                changed = True
                continue
            if node.status in {"draft", "pending"} and parent.support_score >= activation_threshold:
                node.status = "active"
                node.activated_at_round = node.activated_at_round or round_id
                node.updated_at_round = round_id
                if not any(item.round == round_id and item.event == "auto_activation" for item in node.support_history):
                    node.support_history.append(
                        SupportHistoryEntry(
                            round=round_id,
                            score=node.support_score,
                            event="auto_activation",
                        )
                    )
                changed = True


def _support_after_from_assessment(
    *,
    before: float,
    assessment,
    prediction,
    observed_delta: float,
) -> float:
    prior = min(max(before, 0.05), 0.95)
    evidence_support = _assessment_likelihood(
        direction_matched=assessment.direction_matched,
        magnitude_matched=assessment.magnitude_matched,
        prediction=prediction,
        observed_delta=observed_delta,
        favored=True,
    )
    evidence_against = _assessment_likelihood(
        direction_matched=assessment.direction_matched,
        magnitude_matched=assessment.magnitude_matched,
        prediction=prediction,
        observed_delta=observed_delta,
        favored=False,
    )
    numerator = prior * evidence_support
    denominator = numerator + (1.0 - prior) * evidence_against
    if denominator <= 0:
        return round(prior, 4)
    posterior = numerator / denominator
    return round(min(max(posterior, 0.05), 0.95), 4)


def _assessment_likelihood(
    *,
    direction_matched,
    magnitude_matched,
    prediction,
    observed_delta: float,
    favored: bool,
) -> float:
    direction_weight = {
        True: 0.82 if favored else 0.28,
        "partial": 0.62 if favored else 0.45,
        False: 0.24 if favored else 0.80,
    }[direction_matched]
    magnitude_weight = {
        True: 0.76 if favored else 0.36,
        "partial": 0.58 if favored else 0.52,
        False: 0.30 if favored else 0.74,
    }[magnitude_matched]
    precision_weight = _precision_factor(prediction, observed_delta)
    return max(direction_weight * magnitude_weight * precision_weight, 1e-4)


def _precision_factor(prediction, observed_delta: float) -> float:
    expected_range = getattr(prediction, "expected_range", None)
    if not expected_range:
        return 1.0
    lower, upper = expected_range
    hit = lower <= observed_delta <= upper
    width = abs(upper - lower)
    if hit and width < 0.03:
        return 1.05
    if hit and width > 0.10:
        return 0.98
    return 0.95


def _observed_delta_from_evaluation(evaluation: EvaluationResult) -> float:
    if evaluation.metrics.delta.skill is not None:
        return evaluation.metrics.delta.skill
    if evaluation.metrics.delta.pearson_r is not None:
        return evaluation.metrics.delta.pearson_r
    if evaluation.metrics.delta.rmse is not None:
        return -evaluation.metrics.delta.rmse
    return 0.0
