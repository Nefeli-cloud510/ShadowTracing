"""Shared helpers that keep uncertainty-to-hypothesis links alive.

The LLM uncertainty pass frequently omits ``related_hypotheses``, which used to
cascade into empty candidate protocols and an empty hypothesis layer in the
round report.  These helpers provide deterministic fallbacks so a completed
experiment always carries the competing hypotheses it was built to discriminate.
"""

from __future__ import annotations

from core.hypothesis_identity import CANONICAL_DISPLAY_IDS, CANONICAL_HYPOTHESIS_IDS, infer_related_hypothesis_ids
from core.unified_schema import HypothesisNode, HypothesisPrediction, HypothesisTreeState
from core.variable_semantic_service import VariableSemanticService


def related_hypotheses_for_uncertainty(
    tree: HypothesisTreeState | None,
    question: str,
    description: str = "",
    existing: list[str] | None = None,
) -> list[str]:
    """Trust LLM/mined links, then fall back to deterministic text matching."""
    if not question or tree is None:
        return []
    inferred = infer_related_hypothesis_ids(tree, question, description, existing)
    if inferred:
        return inferred

    # Keep a shallow deterministic fallback only; do not over-invent links.
    semantic = VariableSemanticService()
    nodes = [
        node
        for node in tree.nodes
        if node.hypothesis_id in CANONICAL_HYPOTHESIS_IDS
    ]
    text = f"{semantic.display_text(question)} {semantic.display_text(description)}"
    scored = [
        (
            _statement_overlap(characters(text), _statement_characters(node)),
            node,
        )
        for node in nodes
    ]
    ordered = sorted(scored, key=lambda item: item[0], reverse=True)
    selected = [node for score, node in ordered[:2] if score >= 0.5]
    return [node.hypothesis_id for node in selected]


def _statement_characters(node: HypothesisNode) -> str:
    statement = node.display_statement or node.statement or ""
    return "".join(statement.lower().split())


def characters(text: str) -> str:
    if text is None:
        return ""
    return "".join(str(text).lower().split())


def _statement_overlap(question: str, statement: str) -> float:
    if not question or not statement:
        return 0.0
    if statement in question:
        return 1.0
    tokens = statement.replace("？", "").replace("?", "").split("是否")
    terms = [term for term in tokens if term]
    hits = sum(1 for term in terms if term and term in question)
    return hits / max(len(terms), 1) if terms else 0.0


def build_predictions_for_nodes(
    tree: HypothesisTreeState,
    hypothesis_ids: list[str],
) -> dict[str, HypothesisPrediction]:
    """Construct one prediction per selected hypothesis using cached LLM ranges."""
    node_index = tree.node_index()
    predictions: dict[str, HypothesisPrediction] = {}
    for hypothesis_id in hypothesis_ids:
        node = node_index.get(hypothesis_id)
        if node is None:
            continue
        record = next(iter(node.predictions), None)
        expected_effect = (
            str(getattr(record, "expected_direction", "") or "").lower()
            if record is not None
            else "unknown"
        )
        if expected_effect not in {"positive", "negative", "near_zero"}:
            expected_effect = "unknown"
        expected_range = list(getattr(record, "expected_range", None) or [])
        metric = getattr(record, "metric", None) if record is not None else None
        if len(expected_range) != 2:
            confidence = min(max(getattr(node, "support_score", 0.5), 0.05), 0.95)
            width = max(0.015, 0.08 - confidence * 0.04)
            if expected_effect == "negative":
                center = -max(0.02, 0.03 + confidence * 0.05)
            elif expected_effect == "near_zero":
                center = 0.0
            else:
                center = max(0.02, 0.03 + confidence * 0.05)
            expected_range = [round(center - width, 4), round(center + width, 4)]
        predictions[hypothesis_id] = HypothesisPrediction(
            expected_effect=expected_effect,
            expected_range=expected_range,
            metric=metric,
        )
    return predictions
