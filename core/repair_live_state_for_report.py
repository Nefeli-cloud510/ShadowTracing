"""One-shot live-state repair for the report-layer five-item cleanup.

Brings the persisted live session into the canonical H1..H5 hypothesis
skeleton, bounds the active uncertainty queue to 10, and back-fills Pearson
values into stored three-layer conclusions. Run from the repository root:

    python -m core.repair_live_state_for_report --live-root runtime/live_session/current
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from core.hypothesis_generation import HypothesisGenerationService
from core.hypothesis_identity import (
    CANONICAL_DISPLAY_IDS,
    CANONICAL_HYPOTHESIS_IDS,
    infer_related_hypothesis_ids,
    remap_hypothesis_id,
    resolve_hypothesis_display,
)
from core.state_repository import UnifiedStateRepository
from core.unified_schema import (
    LatestTreeUpdate,
    MAX_ACTIVE_UNCERTAINTIES,
    HypothesisSnapshot,
    RoundHistoryEntry,
    TreeSummary,
    UncertaintyHistoryEntry,
)
from core.variable_semantic_service import VariableSemanticService


def _replace_hypothesis_prefix(conclusion: str, old_id: str, display_label: str) -> str:
    if not conclusion or not old_id:
        return conclusion
    stripped = conclusion.lstrip()
    if stripped.startswith(old_id):
        tail = stripped[len(old_id) :].lstrip("：:：_ ,，-—")
        return f"{display_label} {tail}".strip()
    return conclusion


def _backfill_pearson_evidence(
    baseline_r: float | None,
    treatment_r: float | None,
    baseline_rmse: float | None,
    treatment_rmse: float | None,
    horizon_days: int | None,
) -> str:
    if baseline_r is not None and treatment_r is not None:
        evidence = (
            f"ΔPearson r={treatment_r - baseline_r:+.4f}，"
            f"Pearson r {baseline_r:.4f} → {treatment_r:.4f}"
        )
    elif baseline_r is not None or treatment_r is not None:
        evidence = f"Pearson r 未成对取得（对照组={baseline_r}、实验组={treatment_r}）"
    else:
        evidence = "Pearson r 未取得"
    if baseline_rmse is not None and treatment_rmse is not None:
        evidence += f"，RMSE {baseline_rmse:.3f} → {treatment_rmse:.3f}"
    if horizon_days:
        evidence += f"，预测超前 {horizon_days} 天"
    return evidence


def _clean_hypothesis_id_text(
    text: str | None,
    tree,
    semantic: VariableSemanticService,
) -> str:
    """Replace persisted hypothesis IDs with the user-facing H1..H5 labels."""
    if not text:
        return text or ""
    replacements = []
    for node in tree.nodes:
        resolved = resolve_hypothesis_display(tree, node.hypothesis_id, None, semantic)
        if resolved is None:
            continue
        label = resolved[0]
        if label:
            replacements.append((node.hypothesis_id, label))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    cleaned = text
    for old_id, label in replacements:
        cleaned = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(old_id)}(?![A-Za-z0-9_])",
            label,
            cleaned,
        )
    return cleaned


def _backfill_entry_conclusion(
    entry: RoundHistoryEntry,
    tree,
    semantic: VariableSemanticService,
) -> None:
    conclusion = entry.three_layer_conclusion
    metrics = entry.metrics_snapshot
    if conclusion is None:
        return
    if metrics is not None:
        conclusion.experiment_layer.baseline_pearson_r = metrics.baseline_pearson_r
        conclusion.experiment_layer.treatment_pearson_r = metrics.treatment_pearson_r
    deduped_rows: list[Any] = []
    seen_canonical_ids: set[str] = set()
    for row in conclusion.hypothesis_layer:
        original_id = row.hypothesis_id
        resolved = resolve_hypothesis_display(tree, original_id, row.statement, semantic)
        if resolved is None:
            continue
        display_label, canonical_statement = resolved
        canonical_id = remap_hypothesis_id(tree, original_id, row.statement)
        if canonical_id in seen_canonical_ids:
            continue
        seen_canonical_ids.add(canonical_id)
        row.hypothesis_id = remap_hypothesis_id(tree, original_id, row.statement)
        row.display_hypothesis_id = display_label
        row.statement = canonical_statement
        row.conclusion = _replace_hypothesis_prefix(row.conclusion, original_id, display_label)
        row.conclusion = _clean_hypothesis_id_text(row.conclusion, tree, semantic)
        deduped_rows.append(row)
    conclusion.hypothesis_layer = deduped_rows
    if entry.source_experiment_id:
        conclusion.experiment_layer.experiment_id = entry.source_experiment_id
    scientific = conclusion.scientific_layer
    if metrics is not None:
        old_evidence = scientific.evidence_text or ""
        has_legacy_skill_text = bool(re.search(r"(?i)skill|技能增量", old_evidence))
        if has_legacy_skill_text or not old_evidence:
            scientific.evidence_text = _backfill_pearson_evidence(
                metrics.baseline_pearson_r,
                metrics.treatment_pearson_r,
                metrics.baseline_rmse,
                metrics.treatment_rmse,
                conclusion.experiment_layer.forecast_horizon_days,
            )
    scientific.main_question = semantic.display_text(scientific.main_question)
    scientific.answer = semantic.display_text(scientific.answer)
    scientific.evidence_text = _clean_hypothesis_id_text(
        semantic.display_text(scientific.evidence_text),
        tree,
        semantic,
    )


def _canonicalize_references(
    *,
    tree,
    entries: list[RoundHistoryEntry],
) -> None:
    for entry in entries:
        entry.tested_hypotheses = [
            remap_hypothesis_id(tree, item, None)
            for item in entry.tested_hypotheses
        ]
        entry.tested_hypotheses = list(dict.fromkeys(entry.tested_hypotheses))
        entry.highlighted_hypotheses = [
            remap_hypothesis_id(tree, item, None)
            for item in entry.highlighted_hypotheses
        ]
        entry.highlighted_hypotheses = list(dict.fromkeys(entry.highlighted_hypotheses))


def _clean_round_history_text(
    tree,
    entries: list[RoundHistoryEntry],
    semantic: VariableSemanticService,
) -> None:
    for entry in entries:
        entry.scientific_findings = [
            _clean_hypothesis_id_text(item, tree, semantic)
            for item in entry.scientific_findings
        ]
        entry.iteration_input_sources = [
            _clean_hypothesis_id_text(item, tree, semantic)
            for item in entry.iteration_input_sources
        ]
        for checklist_item in entry.closure_checklist:
            if checklist_item.detail:
                checklist_item.detail = _clean_hypothesis_id_text(
                    checklist_item.detail,
                    tree,
                    semantic,
                )


def _dedupe_hypothesis_mapping(
    mapping: dict[str, Any],
    tree,
) -> dict[str, Any]:
    deduped: dict[str, Any] = {}
    for old_id, value in mapping.items():
        canonical_id = remap_hypothesis_id(tree, old_id, None)
        if canonical_id not in deduped:
            deduped[canonical_id] = value
    return deduped


def _canonicalize_candidate_experiments(
    tree,
    repository: UnifiedStateRepository,
) -> dict[str, int]:
    candidates = repository.load_candidate_experiments()
    rows_updated = 0
    for candidate in candidates.candidates:
        remapped = [
            remap_hypothesis_id(tree, item, None)
            for item in candidate.tested_hypotheses
        ]
        candidate.tested_hypotheses = list(dict.fromkeys(remapped))
        if candidate.hypothesis_predictions:
            candidate.hypothesis_predictions = _dedupe_hypothesis_mapping(
                candidate.hypothesis_predictions,
                tree,
            )
        if candidate.disagreement_context:
            candidate.disagreement_context = _dedupe_hypothesis_mapping(
                candidate.disagreement_context,
                tree,
            )
        if candidate.hypothesis_source_context:
            candidate.hypothesis_source_context = _dedupe_hypothesis_mapping(
                candidate.hypothesis_source_context,
                tree,
            )
        rows_updated += 1
    repository.save_candidate_experiments(candidates)
    return {"candidate_rows_remapped": rows_updated}


def _dedupe_hypothesis_ids(tree, ids: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            remap_hypothesis_id(tree, item, None)
            for item in ids
        )
    )


def _canonicalize_planner_input(
    tree,
    planner_input,
    semantic: VariableSemanticService,
) -> None:
    canonical_nodes = [
        node
        for node in tree.nodes
        if node.hypothesis_id in CANONICAL_HYPOTHESIS_IDS
    ]
    canonical_by_id = {node.hypothesis_id: node for node in canonical_nodes}

    planner_input.active_hypotheses = [
        HypothesisSnapshot(
            hypothesis_id=node.hypothesis_id,
            statement=node.display_statement or node.statement,
            status=node.status,
            support_score=node.support_score,
        )
        for node in canonical_nodes
        if node.hypothesis_id in set(tree.active_hypotheses)
    ] or []

    for assessment in planner_input.recent_hypothesis_assessments:
        assessment.hypothesis_id = remap_hypothesis_id(tree, assessment.hypothesis_id, None)
    deduped_assessments = []
    seen_assessment_ids: set[str] = set()
    for assessment in planner_input.recent_hypothesis_assessments:
        if assessment.hypothesis_id in seen_assessment_ids:
            continue
        seen_assessment_ids.add(assessment.hypothesis_id)
        deduped_assessments.append(assessment)
    planner_input.recent_hypothesis_assessments = deduped_assessments

    for item in planner_input.unresolved_uncertainties:
        item.related_hypotheses = _dedupe_hypothesis_ids(tree, item.related_hypotheses)

    for update in planner_input.recent_disagreement_updates:
        update.compared_hypotheses = _dedupe_hypothesis_ids(tree, update.compared_hypotheses)
        update.unresolved_hypotheses = _dedupe_hypothesis_ids(tree, update.unresolved_hypotheses)
        if update.leading_hypothesis_id:
            update.leading_hypothesis_id = remap_hypothesis_id(
                tree,
                update.leading_hypothesis_id,
                None,
            )
        update.summary = _clean_hypothesis_id_text(update.summary, tree, semantic)

    for trace in planner_input.recent_reasoning_traces:
        trace.related_hypotheses = _dedupe_hypothesis_ids(tree, trace.related_hypotheses)
        trace.summary = _clean_hypothesis_id_text(trace.summary, tree, semantic)


def _compress_tree_to_canonical_skeleton(tree) -> None:
    """Strip legacy migration nodes so the display tree is exactly H1..H5."""
    canonical_by_id = {
        node.hypothesis_id: node
        for node in tree.nodes
        if node.hypothesis_id in CANONICAL_HYPOTHESIS_IDS
    }
    ordered = [
        canonical_by_id[node_id]
        for node_id in CANONICAL_HYPOTHESIS_IDS
        if node_id in canonical_by_id
    ]
    canonical_ids = {node.hypothesis_id for node in ordered}
    for node in ordered:
        node.children_ids = [
            child_id
            for child_id in node.children_ids
            if child_id in canonical_ids
        ]
    tree.active_hypotheses = [
        node_id
        for node_id in dict.fromkeys(tree.active_hypotheses)
        if node_id in canonical_ids
    ]
    tree.pruned_hypotheses = [
        node_id
        for node_id in dict.fromkeys(tree.pruned_hypotheses)
        if node_id in canonical_ids
    ]
    tree.pending_hypotheses = [
        node_id
        for node_id in dict.fromkeys(tree.pending_hypotheses)
        if node_id in canonical_ids
    ]
    tree.nodes = ordered
    active_count = len(tree.active_hypotheses)
    pruned_count = len(tree.pruned_hypotheses)
    tree.tree_summary = TreeSummary(
        total_nodes=len(ordered),
        active_count=active_count,
        pruned_count=pruned_count,
        pending_count=len(tree.pending_hypotheses),
    )
    tree.latest_update = LatestTreeUpdate(
        round=tree.current_round,
        event="report_repair_canonical_tree",
        description="报告语义层把假设空间收敛为官方 H1..H5 五个节点。",
    )


def repair_live_state(live_root: str | Path) -> dict[str, Any]:
    live_root = Path(live_root)
    repository = UnifiedStateRepository(live_root)
    task = repository.load_task()
    data_dictionary = repository.load_data_dictionary()
    uncertainties = repository.load_uncertainties()
    tree = repository.load_hypothesis_tree()
    round_history = repository.load_round_history()
    planner_input = repository.load_planner_input()
    current_round = max(round_history.current_round, tree.current_round, 2)

    generated = HypothesisGenerationService().build_tree(
        task=task,
        data_dictionary=data_dictionary,
        uncertainties=uncertainties,
        existing_tree=tree,
        current_round=current_round,
    )
    tree = generated.tree
    canonical_ids = {
        node.hypothesis_id
        for node in tree.nodes
        if node.display_hypothesis_id in {"H1", "H2", "H3", "H4", "H5"}
    }

    semantic = VariableSemanticService.from_data_dictionary(data_dictionary)
    changed_uncertainties = 0
    for record in uncertainties.records:
        inferred = infer_related_hypothesis_ids(
            tree,
            record.question or "",
            record.description or "",
            record.related_hypotheses,
        )
        if inferred and inferred != record.related_hypotheses:
            record.related_hypotheses = inferred
            changed_uncertainties += 1

    queue_order = [
        item.uncertainty_id
        for item in (uncertainties.priority_queue.queue if uncertainties.priority_queue else [])
    ]
    active = [
        record
        for record in uncertainties.records
        if record.status not in {"resolved", "deprecated"}
    ]
    queue_prioritized = [
        item for item in queue_order
        if any(record.uncertainty_id == item for record in active)
    ]
    ordered = queue_prioritized
    ordered += [record.uncertainty_id for record in active if record.uncertainty_id not in ordered]
    selected = list(dict.fromkeys(ordered))[:MAX_ACTIVE_UNCERTAINTIES]
    deprecated = 0
    for record in active:
        if record.uncertainty_id in selected:
            continue
        record.status = "deprecated"
        deprecated += 1
        if not any(
            entry.event == "deprecated_by_report_repair"
            for entry in record.history
        ):
            record.history.append(
                UncertaintyHistoryEntry(
                    round=current_round,
                    event="deprecated_by_report_repair",
                    source="report_repair",
                    description="活跃不确定性超出每轮 10 条上限，由修复脚本置为废弃以保持队列可控。",
                )
            )

    for entry in round_history.entries:
        _backfill_entry_conclusion(entry, tree, semantic)
    _canonicalize_references(tree=tree, entries=round_history.entries)
    _clean_round_history_text(tree, round_history.entries, semantic)
    candidate_stats = _canonicalize_candidate_experiments(tree, repository)
    _canonicalize_planner_input(tree, planner_input, semantic)

    _compress_tree_to_canonical_skeleton(tree)
    repository.save_hypothesis_tree(tree)
    repository.save_uncertainties(uncertainties)
    repository.save_round_history(round_history)
    repository.save_planner_input(planner_input)

    return {
        "live_root": str(live_root),
        "current_round": current_round,
        "canonical_hypothesis_ids": sorted(canonical_ids),
        "tree_nodes": len(tree.nodes),
        "uncertainty_records": len(uncertainties.records),
        "active_uncertainties": len(selected),
        "deprecated_uncertainties": deprecated,
        "uncertainty_links_remapped": changed_uncertainties,
        "round_history_entries": len(round_history.entries),
        "candidate_rows_remapped": candidate_stats["candidate_rows_remapped"],
        "compressed_tree_nodes": len(tree.nodes),
        "planner_assessments": len(planner_input.recent_hypothesis_assessments),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Align live session state with the five-item report cleanup.")
    parser.add_argument(
        "--live-root",
        default="runtime/live_session/current",
        help="live session root, defaults to runtime/live_session/current",
    )
    args = parser.parse_args()
    result = repair_live_state(args.live_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
