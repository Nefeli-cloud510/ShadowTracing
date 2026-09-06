"""Helpers for keeping hypothesis labels aligned across the five canonical slots."""

from __future__ import annotations

import difflib

from core.unified_schema import HypothesisNode, HypothesisTreeState
from core.variable_semantic_service import VariableSemanticService


CANONICAL_DISPLAY_IDS = ("H1", "H2", "H3", "H4", "H5")
CANONICAL_HYPOTHESIS_IDS = (
    "H_shadow_incremental_gain",
    "H_by_mediated_path",
    "H_by_beyond_effect",
    "H_lead_time_window",
    "H_window_stability",
)
GAN_PATTERNS = ("gain", "增益")
PATH_PATTERNS = ("mediated", "mediator", "中介", "路径", "伴随", "branch", "via")
BEYOND_PATTERNS = ("beyond", "independent", "独立于", "独立预测")
WINDOW_PATTERNS = ("lead_time", "horizon_scan", "lag_scan", "窗口", "超前")
STABILITY_PATTERNS = ("window_stability", "temporal_stability", "robustness_window", "stability_refinement")


def canonical_nodes(tree: HypothesisTreeState) -> list[HypothesisNode]:
    """Return the five canonical skeleton nodes in H1..H5 order."""
    by_display = {
        node.display_hypothesis_id: node
        for node in tree.nodes
        if node.hypothesis_id in CANONICAL_HYPOTHESIS_IDS
    }
    return [by_display[label] for label in CANONICAL_DISPLAY_IDS if label in by_display]


def find_best_canonical_node(
    tree: HypothesisTreeState,
    statement: str | None,
) -> HypothesisNode | None:
    """Match legacy text to the closest canonical H1..H5 node."""
    candidates = canonical_nodes(tree)
    if not candidates or not statement:
        return None

    def text(node: HypothesisNode) -> str:
        return node.display_statement or node.statement

    scored = [
        (difflib.SequenceMatcher(None, statement, text(node)).ratio(), node)
        for node in candidates
    ]
    best_score, best_node = max(scored, key=lambda item: item[0])
    if best_score < 0.3:
        return None
    return best_node


def resolve_hypothesis_display(
    tree: HypothesisTreeState,
    hypothesis_id: str,
    statement: str | None = None,
    semantic: VariableSemanticService | None = None,
) -> tuple[str, str] | None:
    """Return ``(display_label, display_statement)`` for a hypothesis reference."""
    node_index = tree.node_index()
    node = node_index.get(hypothesis_id)
    canonical_id = remap_hypothesis_id(tree, hypothesis_id, statement)
    canonical = node_index.get(canonical_id)
    if canonical is None or canonical.hypothesis_id not in CANONICAL_HYPOTHESIS_IDS:
        if canonical is None or not canonical.hypothesis_id.startswith("H_supplemental_"):
            canonical = find_best_canonical_node(
                tree,
                statement or (node.statement if node else ""),
            )
    if canonical is None:
        canonical = node
    if canonical is None:
        return None
    label = canonical.display_hypothesis_id or f"H{canonical.level}"
    return label, display_text(canonical.display_statement or canonical.statement, semantic)
    return None


def remap_hypothesis_id(
    tree: HypothesisTreeState,
    hypothesis_id: str,
    statement: str | None = None,
) -> str:
    """Translate a legacy hypothesis id to its canonical counterpart."""
    if hypothesis_id in CANONICAL_HYPOTHESIS_IDS:
        return hypothesis_id
    if str(hypothesis_id).startswith("H_supplemental_"):
        return hypothesis_id
    node = tree.node_index().get(hypothesis_id)
    pattern_id = _canonical_id_from_legacy_pattern(hypothesis_id)
    if pattern_id is not None:
        return pattern_id
    canonical = find_best_canonical_node(
        tree,
        statement or (node.statement if node else ""),
    )
    return canonical.hypothesis_id if canonical is not None else hypothesis_id


def _canonical_id_from_legacy_pattern(hypothesis_id: str) -> str | None:
    """Deterministic legacy-id fallback used before fuzzy statement matching."""
    lower = hypothesis_id.lower()
    if any(token in lower for token in ("lead_time", "lag_scan", "horizon_scan")):
        return "H_lead_time_window"
    if any(token in lower for token in ("window_stability", "temporal_stability", "robustness_window", "stability_refinement")):
        return "H_window_stability"
    if "independent_gain" in lower or "incremental_gain" in lower or "shadow_incremental_gain" in lower:
        return "H_shadow_incremental_gain"
    if any(token in lower for token in ("null_competition", "branch_", "via_", "mediated")):
        return "H_by_mediated_path"
    if any(token in lower for token in ("conditioned_on_", "conditioned_by_by", "beyond")):
        return "H_by_beyond_effect"
    return None


def infer_related_hypothesis_ids(
    tree: HypothesisTreeState,
    question: str,
    description: str = "",
    existing: list[str] | None = None,
) -> list[str]:
    """Pick the canonical hypotheses an uncertainty actually discriminates.

    ``existing`` links from the miner are trusted when they name one or two
    competing hypotheses; the generic ``[H1, H2, H3]`` fallback produced by
    older code is discarded and replaced with text-derived links instead.
    """
    canonical = canonical_nodes(tree)
    by_label = {node.display_hypothesis_id: node.hypothesis_id for node in canonical}
    if not by_label:
        return list(dict.fromkeys(remap_hypothesis_id(tree, hid) for hid in (existing or [])))

    text = "".join(f"{question} {description}".lower().split())
    labels: list[str] = []

    def add(label: str) -> None:
        if label in by_label and label not in labels:
            labels.append(label)

    if any(token in text for token in ("增益效果", "观测增益", "有无增益", "增量", "independent_gain", "独立增量")):
        add("H1")
    if any(
        token in text
        for token in (
            "主要通过",
            "路径",
            "伴随",
            "中介",
            "mediator",
            "行星际磁场y分量",
            "行星际磁场z分量",
            "行星际磁场总量",
            "kp地磁指数",
            "分歧",
            "竞争",
            "via",
            "branch",
        )
    ):
        add("H2")
    if any(token in text for token in ("超越", "beyond", "之外携带", "额外的预测", "独立预测信息")):
        add("H3")
    if any(token in text for token in ("窗口", "超前", "滞后", "lag", "lead", "提前")):
        add("H4")
    if any(token in text for token in ("稳定", "stability", "时间片", "稳健")):
        add("H5")

    trusted_existing = [remap_hypothesis_id(tree, hid) for hid in (existing or [])]
    trusted_existing = [hid for hid in dict.fromkeys(trusted_existing) if hid in by_label.values()]
    generic_fallback = {by_label.get(label) for label in ("H1", "H2", "H3")} == set(trusted_existing)
    if trusted_existing and not generic_fallback:
        for hid in trusted_existing:
            label = next(
                (label for label, canonical_id in by_label.items() if canonical_id == hid),
                "",
            )
            if label:
                add(label)

    ordered = [by_label[label] for label in ("H1", "H2", "H3", "H4", "H5") if label in labels]
    return ordered or trusted_existing[:2]


def display_text(
    text: str | None,
    semantic: VariableSemanticService | None,
) -> str:
    if text is None:
        return ""
    return semantic.display_text(text) if semantic is not None else text
