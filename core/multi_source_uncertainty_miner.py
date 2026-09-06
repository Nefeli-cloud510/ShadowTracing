"""Multi-source uncertainty miner for the Shadow Tracing closed loop.

The miner consumes five families of evidence:
1. hypothesis-conflict: competing branches that still overlap in support
2. residual-pattern: instability flags and metric deltas from the last round
3. support-shift: before/after hypothesis support movement
4. failure-attribution: execution failures and reasoning-trace caveats
5. missing-evidence: active hypotheses without explicit uncertainty coverage

Mined candidates are prompt-only scientific clues for the LLM questioner and
are never written into the uncertainty queue themselves, so a weak LLM batch
cannot be silently padded with programmatic template records.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from core.state_repository import UnifiedStateRepository
from core.unified_schema import (
    DataDictionary,
    HypothesisTreeState,
    ReasoningPlannerInput,
    ScientificTask,
    UncertaintyRecord,
    UncertaintyState,
)
from core.variable_semantic_service import VariableSemanticService

MIN_UNCERTAINTIES = 4
MAX_ENUMERATED = 10
SOURCE_HYPOTHESIS_CONFLICT = "from_hypothesis_conflict"
SOURCE_RESIDUAL_PATTERN = "from_residual_pattern"
SOURCE_SUPPORT_SHIFT = "from_support_shift"
SOURCE_FAILURE_ATTRIBUTION = "from_failed_execution"
SOURCE_MISSING_EVIDENCE = "from_missing_evidence"

SOURCE_LABELS = {
    SOURCE_HYPOTHESIS_CONFLICT: "假设竞争分歧",
    SOURCE_RESIDUAL_PATTERN: "实验残差模式",
    SOURCE_SUPPORT_SHIFT: "假设支持度变化",
    SOURCE_FAILURE_ATTRIBUTION: "失败归因",
    SOURCE_MISSING_EVIDENCE: "缺失证据",
}


@dataclass(frozen=True)
class MinedUncertaintyCandidate:
    question: str
    description: str
    source_labels: list[str]
    related_hypotheses: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    priority: str = "medium"
    evidence_excerpt: str = ""

    def question_type_hint(self) -> str:
        text = f"{self.question} {self.description}".lower()
        if any(token in text for token in ("滞后", "lag", "稳定", "窗口", "时间片")):
            return "stability"
        if any(token in text for token in ("中介", "mediat", "路径")):
            return "mechanism"
        if any(token in text for token in ("独立", "independent", "增量")):
            return "independent_gain"
        return "distinguishing"

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "description": self.description,
            "source": SOURCE_LABELS.get(self.source_labels[0], "未知来源") if self.source_labels else "未知来源",
            "source_labels": list(self.source_labels),
            "related_hypotheses": list(self.related_hypotheses),
            "features": list(self.features),
            "priority": self.priority,
            "evidence_excerpt": self.evidence_excerpt,
        }


@dataclass(frozen=True)
class MiningContext:
    round_id: int
    task: ScientificTask | None
    planner_input: ReasoningPlannerInput | None
    hypothesis_tree: HypothesisTreeState | None
    uncertainties: UncertaintyState | None
    old_tree: HypothesisTreeState | None = None
    evaluation_summary: dict[str, Any] = field(default_factory=dict)
    closure: dict[str, Any] = field(default_factory=dict)
    failure_records: list[dict[str, Any]] = field(default_factory=list)
    reasoning_traces: list[dict[str, Any]] = field(default_factory=list)
    hypothesis_assessments: list[dict[str, Any]] = field(default_factory=list)
    disagreements: list[dict[str, Any]] = field(default_factory=list)


class MultiSourceUncertaintyMiner:
    """Enumerate, dedupe and merge source-labelled uncertainty candidates."""

    def __init__(self, repository: UnifiedStateRepository | None = None) -> None:
        self.repository = repository

    def mine(self, *, context: MiningContext | None = None, **kwargs: Any) -> MiningResult:
        context = context or self._build_context(**kwargs)
        details = {
            "hypothesis_conflict": self._mine_hypothesis_conflicts(context),
            "residual_pattern": self._mine_residual_patterns(context),
            "support_shift": self._mine_support_shifts(context),
            "failure_attribution": self._mine_failure_attributions(context),
            "missing_evidence": self._mine_missing_evidence(context),
        }
        candidates = _display_candidates(
            context,
            [
                *details["hypothesis_conflict"],
                *details["residual_pattern"],
                *details["support_shift"],
                *details["failure_attribution"],
                *details["missing_evidence"],
            ],
        )
        candidates = _dedupe_candidates(candidates)[:MAX_ENUMERATED]
        records = (
            list(context.uncertainties.records)
            if context.uncertainties
            else []
        )
        return MiningResult(
            candidates=candidates,
            source_detail_counts={
                key: len(value) for key, value in details.items()
            },
            added_uncertainty_ids=[],
            skipped_duplicate_count=0,
            updated_uncertainties=records,
        )

    def _build_context(self, **kwargs: Any) -> MiningContext:
        repo = self.repository
        planner_input = kwargs.get("planner_input")
        tree = kwargs.get("hypothesis_tree") or (repo.load_hypothesis_tree() if repo else None)
        uncertainties = kwargs.get("uncertainties") or (repo.load_uncertainties() if repo else None)
        snapshot = kwargs.get("snapshot") or {}
        old_tree_payload = (
            ((snapshot.get("artifacts") or {}).get("hypothesis_tree"))
            if snapshot
            else kwargs.get("old_tree")
        )
        old_tree = _tree_from_payload(old_tree_payload)
        evaluation_summary = dict(kwargs.get("evaluation_summary") or {})
        if getattr(planner_input, "evaluation_summary", None) is not None:
            evaluation_summary.update(
                planner_input.evaluation_summary.model_dump(exclude_none=True, mode="json")
            )
        closure = (snapshot.get("closure") or {}) if snapshot else (kwargs.get("closure") or {})
        failure_records = [
            record.model_dump(mode="json", exclude_none=True)
            for record in (repo.load_failure_history().records if repo else [])
        ]
        reasoning_traces = [
            trace.model_dump(mode="json", exclude_none=True)
            for trace in getattr(planner_input, "recent_reasoning_traces", []) or []
        ]
        hypothesis_assessments = [
            item.model_dump(mode="json", exclude_none=True)
            for item in getattr(planner_input, "recent_hypothesis_assessments", []) or []
        ]
        disagreements = [
            item.model_dump(mode="json", exclude_none=True)
            for item in getattr(planner_input, "recent_disagreement_updates", []) or []
        ]
        return MiningContext(
            round_id=kwargs.get("round_id") or getattr(planner_input, "next_round_id", 1) or 1,
            task=kwargs.get("task") or (repo.load_task() if repo else None),
            planner_input=planner_input,
            hypothesis_tree=tree,
            uncertainties=uncertainties,
            old_tree=old_tree,
            evaluation_summary=evaluation_summary,
            closure=closure,
            failure_records=failure_records,
            reasoning_traces=reasoning_traces,
            hypothesis_assessments=hypothesis_assessments,
            disagreements=disagreements,
        )

    def _mine_hypothesis_conflicts(self, context: MiningContext) -> list[MinedUncertaintyCandidate]:
        tree = context.hypothesis_tree
        if tree is None or not tree.nodes:
            return []
        node_index = tree.node_index()
        feature_pool = _feature_pool(context)
        planner_features = _planner_features(context.planner_input)
        target = _target(context)
        candidates: list[MinedUncertaintyCandidate] = []

        for left in tree.nodes:
            if left.status in {"pruned", "retracted"}:
                continue
            for right in tree.nodes:
                if right.hypothesis_id <= left.hypothesis_id or right.status in {"pruned", "retracted"}:
                    continue
                gap = abs((left.support_score or 0.0) - (right.support_score or 0.0))
                semantic = _semantic(context)
                left_features = _features_from_text(
                    f"{left.statement} {_rationale_text(left)}",
                    feature_pool,
                    semantic,
                )
                right_features = _features_from_text(
                    f"{right.statement} {_rationale_text(right)}",
                    feature_pool,
                    semantic,
                )
                pair_features = _unique_preserve_order([*left_features, *right_features])[:4]
                if not pair_features:
                    pair_features = _unique_preserve_order([*planner_features, *feature_pool])[:2]
                if gap < 0.08 and set(left_features) == set(right_features):
                    continue
                candidates.append(
                    MinedUncertaintyCandidate(
                        question=(
                            f"{left.hypothesis_id} 与 {right.hypothesis_id} 的分歧是否能在"
                            f"{'、'.join(pair_features) or target} 上通过对照实验直接区分？"
                        ),
                        description=(
                            f"两个竞争假设当前支持度分别为 {left.support_score:.2f} 与 {right.support_score:.2f}，"
                            f"需要设计对比实验判定其解释差异，避免并存假说被同一条证据同时支持。"
                        ),
                        source_labels=[SOURCE_HYPOTHESIS_CONFLICT],
                        related_hypotheses=[left.hypothesis_id, right.hypothesis_id],
                        features=pair_features,
                        priority="high" if gap >= 0.2 else ("medium" if gap >= 0.08 else "low"),
                        evidence_excerpt=(
                            f"support_gap:{gap:.2f}; "
                            f"left:{(left.statement or '')[:90]}; right:{(right.statement or '')[:90]}"
                        ),
                    )
                )
                if len(candidates) >= 6:
                    break
            if len(candidates) >= 6:
                break
        return candidates

    def _mine_residual_patterns(self, context: MiningContext) -> list[MinedUncertaintyCandidate]:
        summary = context.evaluation_summary or {}
        stable = summary.get("stable")
        candidates: list[MinedUncertaintyCandidate] = []
        base_features = _feature_pool(context)[:3] or [_target(context)]
        primary = base_features[0]
        target = _target(context)
        delta_rmse = summary.get("delta_rmse")
        delta_pearson = summary.get("delta_pearson_r")
        instability_reason = summary.get("robustness_recommendation") or ""

        if stable is False or "稳定" in instability_reason or "robust" in instability_reason.lower():
            candidates.append(
                MinedUncertaintyCandidate(
                    question=f"{primary} 对 {target} 的增益是否只在局部时间窗口成立？",
                    description=(
                        f"上一轮评价显示结果稳定性不足（{instability_reason[:80] or 'time-slice/bootstrap 波动'}），"
                        f"需要补做时间片与窗口敏感性检验，避免把局部提升误判为普遍规律。"
                    ),
                    source_labels=[SOURCE_RESIDUAL_PATTERN],
                    related_hypotheses=_top_hypotheses(context, 2),
                    features=[primary, target] if primary != target else [primary],
                    priority="high",
                    evidence_excerpt=f"stable={stable}; recommendation={instability_reason[:120]}",
                )
            )

        if isinstance(delta_rmse, (int, float)) and math.isfinite(delta_rmse) and delta_rmse > 0.0:
            candidates.append(
                MinedUncertaintyCandidate(
                    question=f"当前 {primary} 模型的剩余误差是否仍集中出现在特定时段或极端事件？",
                    description=(
                        f"上一轮 RMSE 变化为 {delta_rmse:.4f}，残差结构可能携带未被建模的时间段或事件模式；"
                        f"需要结合残差切片定位误差来源。"
                    ),
                    source_labels=[SOURCE_RESIDUAL_PATTERN],
                    related_hypotheses=_top_hypotheses(context, 2),
                    features=[primary, target] if primary != target else [primary],
                    priority="medium",
                    evidence_excerpt=f"delta_rmse={delta_rmse}",
                )
            )

        if isinstance(delta_pearson, (int, float)) and math.isfinite(delta_pearson) and delta_pearson < 0.0:
            candidates.append(
                MinedUncertaintyCandidate(
                    question=f"{primary} 的预测相关性下降是否来自竞争变量遗漏或时间滞后错配？",
                    description=(
                        f"上一轮 Pearson_r 变化为 {delta_pearson:.4f}，需要检查 {primary} 与 {target} 的滞后设定、"
                        f"竞争特征遗漏以及极端样本影响。"
                    ),
                    source_labels=[SOURCE_RESIDUAL_PATTERN],
                    related_hypotheses=_top_hypotheses(context, 2),
                    features=[primary, target] if primary != target else [primary],
                    priority="medium",
                    evidence_excerpt=f"delta_pearson_r={delta_pearson}",
                )
            )

        trace_evidence = [
            trace.get("summary", "")
            for trace in context.reasoning_traces
            if any(token in str(trace.get("summary", "")) for token in ("残差", "residual", "误差", "error", "失败归因", "fail"))
        ]
        if trace_evidence and not candidates:
            candidates.append(
                MinedUncertaintyCandidate(
                    question=f"{primary} 的解释是否遗漏了推理日志中提示的残差或失败归因？",
                    description=(
                        f"推理轨迹提示：{trace_evidence[0][:120]}。需要将残差结构转化为可执行实验，"
                        f"检验 {primary} 是否只是代理变量。"
                    ),
                    source_labels=[SOURCE_RESIDUAL_PATTERN],
                    related_hypotheses=_top_hypotheses(context, 2),
                    features=[primary, target] if primary != target else [primary],
                    priority="medium",
                    evidence_excerpt=trace_evidence[0][:160],
                )
            )
        return candidates[:4]

    def _mine_support_shifts(self, context: MiningContext) -> list[MinedUncertaintyCandidate]:
        current = _node_scores(context.hypothesis_tree)
        previous = {
            item.get("hypothesis_id"): item.get("support_before")
            for item in context.hypothesis_assessments
            if item.get("hypothesis_id") and item.get("support_before") is not None
        }
        if not previous:
            previous = _node_scores(context.old_tree)
        target = _target(context)
        candidates: list[MinedUncertaintyCandidate] = []
        moves = [
            (hypothesis_id, delta, before, after)
            for hypothesis_id, after in current.items()
            if hypothesis_id in previous and previous[hypothesis_id] is not None
            for delta, before, _after in [
                (after - previous[hypothesis_id], previous[hypothesis_id], after),
            ]
        ]
        moves.sort(key=lambda item: abs(item[1]), reverse=True)
        features = _feature_pool(context)[:4] or [target]

        for index, (hypothesis_id, delta, before, after) in enumerate(moves[:3], start=1):
            direction = "上升" if delta >= 0 else "下降"
            candidates.append(
                MinedUncertaintyCandidate(
                    question=(
                        f"{hypothesis_id} 支持度{direction}（{before:.2f}→{after:.2f}）是否反映真实证据，"
                        f"而非受 {'/'.join(features[:2])} 的窗口选择驱动？"
                    ),
                    description=(
                        f"上一轮后假设支持度出现 {abs(delta):.2f} 的变化，需要检验该变化是否稳健、"
                        f"可复现，并确认是否应修改假设激活或剪枝状态。"
                    ),
                    source_labels=[SOURCE_SUPPORT_SHIFT],
                    related_hypotheses=[hypothesis_id],
                    features=features[:3],
                    priority="high" if abs(delta) >= 0.15 else "medium",
                    evidence_excerpt=f"support_before={before:.3f}; support_after={after:.3f}; delta={delta:.3f}",
                )
            )
        return candidates

    def _mine_failure_attributions(self, context: MiningContext) -> list[MinedUncertaintyCandidate]:
        candidates: list[MinedUncertaintyCandidate] = []
        feature_pool = _feature_pool(context)[:3] or [_target(context)]
        target = _target(context)
        for index, record in enumerate(context.failure_records[:3], start=1):
            focus = feature_pool[(index - 1) % len(feature_pool)]
            message = str(record.get("message") or record.get("traceback_excerpt") or "存在执行失败")
            candidates.append(
                MinedUncertaintyCandidate(
                    question=f"上一轮执行失败是否暴露出 {focus} 相关的数据或协议缺口？",
                    description=(
                        f"失败归因记录（{record.get('phase', 'execution')}/{record.get('step', '')}）："
                        f"{message[:100]}。需要先补足数据质量与协议约束，再执行 {focus} 区分实验。"
                    ),
                    source_labels=[SOURCE_FAILURE_ATTRIBUTION],
                    related_hypotheses=_top_hypotheses(context, 1),
                    features=[focus, target] if focus != target else [focus],
                    priority="high",
                    evidence_excerpt=f"failure_id={record.get('failure_id')}; {message[:120]}",
                )
            )

        missing_attribution = [
            trace.get("summary", "")
            for trace in context.reasoning_traces
            if any(token in str(trace.get("summary", "")) for token in ("失败", "fail", "归因", "无法", "异常", "error"))
        ]
        if missing_attribution and not candidates:
            candidates.append(
                MinedUncertaintyCandidate(
                    question=f"闭环日志中的失败线索是否需要在下一轮实验前做归因收口？",
                    description=(
                        f"日志线索：{missing_attribution[0][:120]}。应把失败归因转化为前置检查或协议修正，"
                        f"避免下一轮在同一环节重复失败。"
                    ),
                    source_labels=[SOURCE_FAILURE_ATTRIBUTION],
                    related_hypotheses=_top_hypotheses(context, 1),
                    features=feature_pool[:2],
                    priority="high",
                    evidence_excerpt=missing_attribution[0][:160],
                )
            )
        return candidates[:3]

    def _mine_missing_evidence(self, context: MiningContext) -> list[MinedUncertaintyCandidate]:
        tree = context.hypothesis_tree
        if tree is None:
            return []
        node_to_uncertainty: dict[str, list[str]] = {}
        for record in (context.uncertainties.records if context.uncertainties else []):
            for hypothesis_id in record.related_hypotheses:
                node_to_uncertainty.setdefault(hypothesis_id, []).append(record.uncertainty_id)
        feature_pool = _feature_pool(context)[:4]
        target = _target(context)
        candidates: list[MinedUncertaintyCandidate] = []
        for index, node in enumerate(tree.nodes):
            if node.status in {"pruned", "retracted", "resolved"}:
                continue
            if node_to_uncertainty.get(node.hypothesis_id):
                continue
            if (node.support_score or 0.0) >= 0.75 and node.status == "active":
                continue
            features = _features_from_text(
                f"{node.statement} {_rationale_text(node)}",
                feature_pool,
                _semantic(context),
            )[:3] or feature_pool[:2] or [target]
            candidates.append(
                MinedUncertaintyCandidate(
                    question=f"{node.hypothesis_id} 尚缺少哪类证据来约束其成立条件？",
                    description=(
                        f"该假设当前支持度 {node.support_score or 0.0:.2f}、状态 {node.status}，"
                        f"尚未被任何不确定性显式追踪；需要围绕 {'、'.join(features)} 与 {target} "
                        f"补充证据缺口。"
                    ),
                    source_labels=[SOURCE_MISSING_EVIDENCE],
                    related_hypotheses=[node.hypothesis_id],
                    features=features,
                    priority="high" if (node.support_score or 0.0) < 0.35 else "medium",
                    evidence_excerpt=f"support={node.support_score or 0.0:.2f}; status={node.status}",
                )
            )
            if len(candidates) >= 4:
                break
        return candidates


@dataclass(frozen=True)
class MiningResult:
    candidates: list[MinedUncertaintyCandidate]
    source_detail_counts: dict[str, int]
    added_uncertainty_ids: list[str]
    skipped_duplicate_count: int
    updated_uncertainties: list[UncertaintyRecord]




def _dedupe_candidates(candidates: list[MinedUncertaintyCandidate]) -> list[MinedUncertaintyCandidate]:
    kept: list[MinedUncertaintyCandidate] = []
    for candidate in candidates:
        if any(_candidate_similar(existing, candidate) for existing in kept):
            continue
        kept.append(candidate)
    return kept


def _candidate_similar(left: MinedUncertaintyCandidate, right: MinedUncertaintyCandidate) -> bool:
    left_text = _normalize(f"{left.question} {left.description}")
    right_text = _normalize(f"{right.question} {right.description}")
    tokens_left = _tokens(left_text)
    tokens_right = _tokens(right_text)
    overlap = len(set(tokens_left) & set(tokens_right)) / max(len(set(tokens_left) | set(tokens_right)), 1)
    hypothesis_overlap = len(set(left.related_hypotheses) & set(right.related_hypotheses)) / max(
        len(set(left.related_hypotheses) | set(right.related_hypotheses)), 1
    )
    feature_overlap = len(set(left.features) & set(right.features)) / max(
        len(set(left.features) | set(right.features)), 1
    )
    if overlap >= 0.78 and (
        (
            len(set(left.related_hypotheses) & set(right.related_hypotheses)) > 0
            and len(set(left.related_hypotheses) | set(right.related_hypotheses)) <= 4
        )
        or feature_overlap >= 0.6
    ):
        return True
    return _normalize(left.question) == _normalize(right.question)


def _node_scores(tree: HypothesisTreeState | None) -> dict[str, float]:
    if tree is None:
        return {}
    return {
        node.hypothesis_id: node.support_score
        for node in tree.nodes
    }


def _tree_from_payload(payload: dict[str, Any] | None) -> HypothesisTreeState | None:
    if not payload:
        return None
    return HypothesisTreeState.model_validate(payload)


def _top_hypotheses(context: MiningContext, limit: int) -> list[str]:
    tree = context.hypothesis_tree
    if tree is None:
        return []
    return [
        node.hypothesis_id
        for node in sorted(
            (node for node in tree.nodes if node.status not in {"pruned", "retracted"}),
            key=lambda node: node.support_score,
            reverse=True,
        )[:limit]
    ]


def _feature_pool(context: MiningContext) -> list[str]:
    summary = getattr(context.planner_input, "data_dictionary_summary", None)
    if summary is None:
        return []
    return _unique_preserve_order([*summary.feature_candidates, *summary.target_candidates])


def _planner_features(planner_input: ReasoningPlannerInput | None) -> list[str]:
    if planner_input is None or planner_input.data_dictionary_summary is None:
        return []
    return _unique_preserve_order(
        [
            *planner_input.data_dictionary_summary.feature_candidates,
            *planner_input.data_dictionary_summary.target_candidates,
        ]
    )


def _target(context: MiningContext) -> str:
    if context.planner_input is not None:
        return context.planner_input.target
    task = context.task
    if task is not None:
        return task.payload.research_question.target
    return "target"


def _rationale_text(node: Any) -> str:
    rationale = getattr(node, "generation_rationale", None)
    if rationale is None:
        return ""
    return " ".join(
        str(item)
        for item in [
            getattr(rationale, "summary", ""),
            *getattr(rationale, "trigger", "").split(";"),
        ]
        if item
    )


def _features_from_text(
    text: str,
    feature_pool: list[str],
    semantic: VariableSemanticService | None = None,
) -> list[str]:
    return [
        feature
        for feature in feature_pool
        if feature and (
            feature.lower() in str(text).lower()
            or (semantic is not None and semantic.matches_text(feature, text))
        )
    ]


def _semantic(context: MiningContext) -> VariableSemanticService:
    summary = getattr(context.planner_input, "data_dictionary_summary", None)
    return VariableSemanticService.from_summary(summary)


def _display_candidates(
    context: MiningContext,
    candidates: list[MinedUncertaintyCandidate],
) -> list[MinedUncertaintyCandidate]:
    semantic = _semantic(context)
    result: list[MinedUncertaintyCandidate] = []
    for candidate in candidates:
        question = semantic.display_text(candidate.question)
        description = semantic.display_text(candidate.description)
        if question == candidate.question and description == candidate.description:
            result.append(candidate)
            continue
        result.append(
            replace(
                candidate,
                question=question,
                description=description,
            )
        )
    return result


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _normalize(text: str) -> str:
    return "".join(str(text).lower().split())


def _tokens(text: str) -> set[str]:
    import re

    return set(re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", text.lower()))
