from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.unified_schema import (
    DataDictionary,
    HypothesisGenerationRationale,
    HypothesisNode,
    HypothesisSourceSignal,
    HypothesisTreeState,
    LatestTreeUpdate,
    PredictionRecord,
    ReasoningPlannerInput,
    ScientificTask,
    TreeSummary,
    UncertaintyRecord,
    UncertaintyState,
)


@dataclass(frozen=True)
class HypothesisGenerationResult:
    tree: HypothesisTreeState
    generated_node_ids: tuple[str, ...]
    updated_uncertainties: tuple[UncertaintyRecord, ...]
    mode: str


class HypothesisGenerationService:
    """Programmatically derive initial or incremental hypothesis trees from task/state context."""

    def build_tree(
        self,
        *,
        task: ScientificTask,
        data_dictionary: DataDictionary,
        uncertainties: list[UncertaintyRecord] | UncertaintyState | None = None,
        planner_input: ReasoningPlannerInput | None = None,
        existing_tree: HypothesisTreeState | None = None,
        current_round: int | None = None,
    ) -> HypothesisGenerationResult:
        current_round = (
            current_round
            if current_round is not None
            else (planner_input.next_round_id if planner_input else (existing_tree.current_round if existing_tree else 0))
        )
        uncertainty_records = _normalize_uncertainties(uncertainties)
        if existing_tree is None or not existing_tree.nodes:
            nodes = self._generate_initial_nodes(
                task=task,
                data_dictionary=data_dictionary,
                uncertainties=uncertainty_records,
                planner_input=planner_input,
                current_round=current_round,
            )
            updated_uncertainties = tuple(self._sync_uncertainty_links(nodes, uncertainty_records))
            tree = _build_tree_state(
                task=task,
                nodes=nodes,
                current_round=current_round,
                event="hypothesis_generated",
                description="programmatic initial hypothesis tree generated from task/data/uncertainty context",
            )
            return HypothesisGenerationResult(
                tree=tree,
                generated_node_ids=tuple(node.hypothesis_id for node in nodes),
                updated_uncertainties=updated_uncertainties,
                mode="initial",
            )

        nodes = [node.model_copy(deep=True) for node in existing_tree.nodes]
        generated = self._generate_incremental_nodes(
            task=task,
            data_dictionary=data_dictionary,
            uncertainties=uncertainty_records,
            planner_input=planner_input,
            nodes=nodes,
            current_round=current_round,
        )
        if generated:
            updated_uncertainties = tuple(self._sync_uncertainty_links(nodes, uncertainty_records))
            _ensure_min_active_hypotheses(
                nodes,
                min_required=task.payload.constraints.min_active_hypotheses or 3,
                current_round=current_round,
            )
            tree = _build_tree_state(
                task=task,
                nodes=nodes,
                current_round=max(existing_tree.current_round, current_round),
                event="hypothesis_generated",
                description=f"programmatic hypothesis generation added {len(generated)} nodes for next-round reasoning",
            )
            return HypothesisGenerationResult(
                tree=tree,
                generated_node_ids=tuple(node.hypothesis_id for node in generated),
                updated_uncertainties=updated_uncertainties,
                mode="incremental",
            )

        return HypothesisGenerationResult(
            tree=existing_tree.model_copy(deep=True),
            generated_node_ids=(),
            updated_uncertainties=tuple(self._sync_uncertainty_links(nodes, uncertainty_records)),
            mode="incremental",
        )

    def _generate_initial_nodes(
        self,
        *,
        task: ScientificTask,
        data_dictionary: DataDictionary,
        uncertainties: list[UncertaintyRecord],
        planner_input: ReasoningPlannerInput | None,
        current_round: int,
    ) -> list[HypothesisNode]:
        primary_x, target, mediators, feature_pool = _task_feature_context(task, data_dictionary)
        nodes: list[HypothesisNode] = []
        existing_ids: set[str] = set()

        gain_node = HypothesisNode(
            hypothesis_id=_unique_hypothesis_id(f"{primary_x}_independent_gain", existing_ids),
            statement=f"{primary_x} 对 {target} 提供可检验的独立增量信息。",
            level=1,
            status="active",
            support_score=0.58 if primary_x in data_dictionary.feature_candidates else 0.5,
            activation_condition="derived from scientific task and current variable binding",
            created_at_round=current_round,
            updated_at_round=current_round,
            predictions=[
                PredictionRecord(
                    experiment_id="task_bootstrap",
                    metric="Pearson_r",
                    expected_direction="positive",
                )
            ],
            falsification_conditions=[f"新增 {primary_x} 后性能没有稳定改善"],
            generation_rationale=_build_generation_rationale(
                trigger="task_bootstrap",
                summary=f"根据 scientific task 中的主变量绑定，先生成 {primary_x} 对 {target} 的独立增量假设。",
                linked_uncertainties=_linked_uncertainty_ids(uncertainties, keywords=[primary_x, "独立", "independent", target]),
                derived_features=[primary_x, target],
                source_signals=_task_bootstrap_signals(task, data_dictionary, uncertainties, primary_x, target),
                confidence=0.72,
            ),
        )
        nodes.append(gain_node)
        existing_ids.add(gain_node.hypothesis_id)

        competition_feature = mediators[0] if mediators else (feature_pool[0] if feature_pool else target)
        null_node = HypothesisNode(
            hypothesis_id=_unique_hypothesis_id(f"{primary_x}_null_competition", existing_ids),
            statement=f"{primary_x} 对 {target} 的观测增益主要来自与 {competition_feature} 的伴随相关，而非独立信息。",
            level=1,
            status="active",
            support_score=0.42,
            activation_condition="kept active as a competing explanation",
            created_at_round=current_round,
            updated_at_round=current_round,
            alternative_explanations=[f"{competition_feature} may explain most observed variation in {target}"],
            generation_rationale=_build_generation_rationale(
                trigger="competition_bootstrap",
                summary=f"为避免只保留单一路径，生成与 {competition_feature} 相关的竞争解释假设。",
                linked_uncertainties=_linked_uncertainty_ids(
                    uncertainties,
                    keywords=[competition_feature, "独立", "中介", "伴随", target],
                ),
                derived_features=[primary_x, competition_feature, target],
                source_signals=_competition_signals(task, uncertainties, competition_feature, target),
                confidence=0.6,
            ),
        )
        nodes.append(null_node)
        existing_ids.add(null_node.hypothesis_id)

        for mediator in mediators[: max(task.payload.constraints.max_hypotheses_per_level or 3, 1)]:
            child = HypothesisNode(
                hypothesis_id=_unique_hypothesis_id(f"{primary_x}_via_{mediator}", existing_ids),
                statement=f"{primary_x} 对 {target} 的作用可能通过 {mediator} 中介路径体现。",
                level=2,
                parent_id=gain_node.hypothesis_id,
                status="pending",
                support_score=0.36,
                activation_condition=f"当 {gain_node.hypothesis_id} 支持度>=0.40 时激活",
                created_at_round=current_round,
                updated_at_round=current_round,
                alternative_explanations=[f"{mediator} may act as mediator or confounder"],
                generation_rationale=_build_generation_rationale(
                    trigger="mediator_bootstrap",
                    summary=f"根据 research question 中的候选中介变量 {mediator}，生成中介路径假设。",
                    linked_uncertainties=_linked_uncertainty_ids(
                        uncertainties,
                        keywords=[mediator, "中介", "mediator", primary_x, target],
                    ),
                    derived_features=[primary_x, mediator, target],
                    source_signals=_mediator_signals(task, uncertainties, mediator),
                    confidence=0.64,
                ),
            )
            gain_node.children_ids.append(child.hypothesis_id)
            nodes.append(child)
            existing_ids.add(child.hypothesis_id)

        if _needs_stability_hypothesis(task, uncertainties):
            stability = HypothesisNode(
                hypothesis_id=_unique_hypothesis_id(f"{primary_x}_temporal_stability", existing_ids),
                statement=f"{primary_x} 对 {target} 的增量在不同时间片和滞后设定下保持稳定。",
                level=2,
                parent_id=gain_node.hypothesis_id,
                status="pending",
                support_score=0.4,
                activation_condition="当系统识别出跨时间或稳健性不确定性时激活",
                created_at_round=current_round,
                updated_at_round=current_round,
                falsification_conditions=["time-slice or lag-sensitivity checks show unstable gain"],
                generation_rationale=_build_generation_rationale(
                    trigger="stability_bootstrap",
                    summary=f"根据任务/不确定性中的时间稳定性信号，生成 {primary_x} 的稳健性假设。",
                    linked_uncertainties=_linked_uncertainty_ids(
                        uncertainties,
                        keywords=["稳定", "stability", "滞后", "time", primary_x],
                    ),
                    derived_features=[primary_x, target],
                    source_signals=_stability_signals(task, uncertainties),
                    confidence=0.68,
                ),
            )
            gain_node.children_ids.append(stability.hypothesis_id)
            nodes.append(stability)
            existing_ids.add(stability.hypothesis_id)

        _ensure_min_active_hypotheses(
            nodes,
            min_required=task.payload.constraints.min_active_hypotheses or 3,
            current_round=current_round,
        )
        return nodes

    def _generate_incremental_nodes(
        self,
        *,
        task: ScientificTask,
        data_dictionary: DataDictionary,
        uncertainties: list[UncertaintyRecord],
        planner_input: ReasoningPlannerInput | None,
        nodes: list[HypothesisNode],
        current_round: int,
    ) -> list[HypothesisNode]:
        primary_x, target, mediators, feature_pool = _task_feature_context(task, data_dictionary)
        node_index = {node.hypothesis_id: node for node in nodes}
        existing_ids = set(node_index)
        generated: list[HypothesisNode] = []
        parent = _select_primary_parent(nodes, primary_x)
        mentioned_statements = " ".join(node.statement.lower() for node in nodes)

        feedback_features = _feedback_features(planner_input, data_dictionary, primary_x, target)
        for feature in feedback_features:
            if feature.lower() in mentioned_statements:
                continue
            node = HypothesisNode(
                hypothesis_id=_unique_hypothesis_id(f"{primary_x}_conditioned_on_{feature}", existing_ids),
                statement=f"{primary_x} 对 {target} 的作用可能依赖 {feature} 条件路径。",
                level=2 if parent else 1,
                parent_id=parent.hypothesis_id if parent else None,
                status="pending",
                support_score=0.38,
                activation_condition=f"当 planner context 或 human feedback 明确关注 {feature} 时激活",
                created_at_round=current_round,
                updated_at_round=current_round,
                alternative_explanations=[f"{feature} may define the boundary condition of {primary_x}'s effect"],
                generation_rationale=_build_generation_rationale(
                    trigger="planner_feature_focus",
                    summary=f"由于 planner context 明确关注 {feature}，生成条件路径假设。",
                    linked_uncertainties=_linked_uncertainty_ids(
                        uncertainties,
                        keywords=[feature, primary_x, "条件", "依赖"],
                    ),
                    derived_features=[primary_x, feature, target],
                    source_signals=_planner_feature_signals(planner_input, feature),
                    confidence=0.7,
                ),
            )
            if parent:
                parent.children_ids.append(node.hypothesis_id)
            nodes.append(node)
            generated.append(node)
            existing_ids.add(node.hypothesis_id)
            mentioned_statements = f"{mentioned_statements} {node.statement.lower()}"

        if _needs_stability_hypothesis(task, uncertainties) and "稳定" not in mentioned_statements and "stability" not in mentioned_statements:
            node = HypothesisNode(
                hypothesis_id=_unique_hypothesis_id(f"{primary_x}_stability_refinement", existing_ids),
                statement=f"{primary_x} 对 {target} 的增量可能只在部分时间窗口稳定，需要额外稳健性验证。",
                level=2 if parent else 1,
                parent_id=parent.hypothesis_id if parent else None,
                status="pending",
                support_score=0.34,
                activation_condition="当上一轮结果提示稳健性不足或时间片分歧时激活",
                created_at_round=current_round,
                updated_at_round=current_round,
                generation_rationale=_build_generation_rationale(
                    trigger="stability_refinement",
                    summary="上一轮上下文继续提示稳健性/时间片分歧，因此扩展稳定性细化假设。",
                    linked_uncertainties=_linked_uncertainty_ids(
                        uncertainties,
                        keywords=["稳定", "stability", "滞后", "time", primary_x],
                    ),
                    derived_features=[primary_x, target],
                    source_signals=_stability_refinement_signals(planner_input, uncertainties),
                    confidence=0.62,
                ),
            )
            if parent:
                parent.children_ids.append(node.hypothesis_id)
            nodes.append(node)
            generated.append(node)
            existing_ids.add(node.hypothesis_id)

        if planner_input and planner_input.recent_hypothesis_assessments:
            weakened = [item for item in planner_input.recent_hypothesis_assessments if item.status in {"weakened"}]
            if weakened and not any("伴随相关" in node.statement or "替代解释" in " ".join(node.alternative_explanations) for node in nodes):
                alternative_feature = feedback_features[0] if feedback_features else (mediators[0] if mediators else (feature_pool[0] if feature_pool else target))
                node = HypothesisNode(
                    hypothesis_id=_unique_hypothesis_id(f"{primary_x}_alternative_explanation", existing_ids),
                    statement=f"{target} 的变化主要可由 {alternative_feature} 解释，{primary_x} 更可能是伴随信号而非独立驱动。",
                    level=1,
                    status="active",
                    support_score=0.41,
                    activation_condition="当上一轮正式评价削弱主假设时保持为竞争假设",
                    created_at_round=current_round,
                    updated_at_round=current_round,
                    generation_rationale=_build_generation_rationale(
                        trigger="weakened_assessment",
                        summary="由于正式评价削弱主假设，补充新的竞争解释节点。",
                        linked_uncertainties=_linked_uncertainty_ids(
                            uncertainties,
                            keywords=[alternative_feature, "解释", "伴随", target],
                        ),
                        derived_features=[primary_x, alternative_feature, target],
                        source_signals=_weakened_assessment_signals(planner_input, alternative_feature),
                        confidence=0.66,
                    ),
                )
                nodes.append(node)
                generated.append(node)
                existing_ids.add(node.hypothesis_id)

        return generated

    def _sync_uncertainty_links(
        self,
        nodes: list[HypothesisNode],
        uncertainties: list[UncertaintyRecord],
    ) -> list[UncertaintyRecord]:
        if not uncertainties:
            return []
        updated = [item.model_copy(deep=True) for item in uncertainties]
        for record in updated:
            linked: list[str] = list(record.related_hypotheses)
            text = f"{record.question} {record.description}".lower()
            for node in nodes:
                rationale = node.generation_rationale
                if rationale and record.uncertainty_id in rationale.linked_uncertainties:
                    linked.append(node.hypothesis_id)
                    continue
                if any(feature.lower() in text for feature in _node_keywords(node)):
                    linked.append(node.hypothesis_id)
            record.related_hypotheses = _unique_preserve_order(linked)
        return updated


def _normalize_uncertainties(
    uncertainties: list[UncertaintyRecord] | UncertaintyState | None,
) -> list[UncertaintyRecord]:
    if uncertainties is None:
        return []
    if isinstance(uncertainties, UncertaintyState):
        return [item.model_copy(deep=True) for item in uncertainties.records]
    return [item.model_copy(deep=True) for item in uncertainties]


def _task_feature_context(
    task: ScientificTask,
    data_dictionary: DataDictionary,
) -> tuple[str, str, list[str], list[str]]:
    variables = task.payload.research_question.variables
    primary_x = variables.x if variables else (data_dictionary.feature_candidates[0] if data_dictionary.feature_candidates else task.payload.research_question.target)
    target = task.payload.research_question.target
    mediators = [item for item in (variables.m_candidates if variables else []) if item in data_dictionary.feature_candidates]
    feature_pool = [item for item in data_dictionary.feature_candidates if item not in {primary_x, target}]
    return primary_x, target, mediators, feature_pool


def _feedback_features(
    planner_input: ReasoningPlannerInput | None,
    data_dictionary: DataDictionary,
    primary_x: str,
    target: str,
) -> list[str]:
    if planner_input is None:
        return []
    corpus: list[str] = []
    if planner_input.human_feedback:
        corpus.append(planner_input.human_feedback.lower())
    corpus.extend(item.content.lower() for item in planner_input.recent_human_feedback)
    corpus.extend(item.summary.lower() for item in planner_input.recent_reasoning_traces)
    corpus.extend(item.lower() for item in planner_input.planner_guidance)
    merged = " ".join(corpus)
    return [
        feature
        for feature in data_dictionary.feature_candidates
        if feature not in {primary_x, target} and feature.lower() in merged
    ]


def _needs_stability_hypothesis(
    task: ScientificTask,
    uncertainties: Iterable[UncertaintyRecord],
) -> bool:
    text = " ".join(
        [task.payload.research_question.text.lower()]
        + [f"{item.question} {item.description}".lower() for item in uncertainties]
    )
    return any(token in text for token in ("稳定", "stability", "lag", "滞后", "time", "跨时间"))


def _select_primary_parent(nodes: list[HypothesisNode], primary_x: str) -> HypothesisNode | None:
    root_candidates = [
        node
        for node in nodes
        if node.parent_id is None and primary_x.lower() in node.statement.lower() and node.status in {"active", "observing", "converged"}
    ]
    if not root_candidates:
        return None
    return max(root_candidates, key=lambda item: item.support_score)


def _ensure_min_active_hypotheses(
    nodes: list[HypothesisNode],
    *,
    min_required: int,
    current_round: int,
) -> None:
    active_count = sum(1 for node in nodes if node.status in {"active", "converged"})
    if active_count >= min_required:
        return
    candidates = sorted(
        [node for node in nodes if node.status in {"draft", "pending", "observing"}],
        key=lambda item: item.support_score,
        reverse=True,
    )
    for node in candidates:
        node.status = "active"
        node.activated_at_round = current_round
        active_count += 1
        if active_count >= min_required:
            break


def _build_tree_state(
    *,
    task: ScientificTask,
    nodes: list[HypothesisNode],
    current_round: int,
    event: str,
    description: str,
) -> HypothesisTreeState:
    return HypothesisTreeState(
        tree_id=f"{task.task_id}_tree",
        task_id=task.task_id,
        current_round=current_round,
        root_question=task.payload.research_question.text,
        nodes=nodes,
        active_hypotheses=[node.hypothesis_id for node in nodes if node.status in {"active", "converged"}],
        pruned_hypotheses=[node.hypothesis_id for node in nodes if node.status == "pruned"],
        pending_hypotheses=[node.hypothesis_id for node in nodes if node.status in {"draft", "pending"}],
        latest_update=LatestTreeUpdate(
            round=current_round,
            event=event,
            description=description,
        ),
        tree_summary=TreeSummary(
            total_nodes=len(nodes),
            active_count=sum(1 for node in nodes if node.status in {"active", "converged"}),
            pruned_count=sum(1 for node in nodes if node.status == "pruned"),
            pending_count=sum(1 for node in nodes if node.status in {"draft", "pending"}),
        ),
    )


def _unique_hypothesis_id(base: str, existing_ids: set[str]) -> str:
    normalized = _slug(base)
    candidate = f"H_{normalized}"
    index = 2
    while candidate in existing_ids:
        candidate = f"H_{normalized}_{index}"
        index += 1
    return candidate


def _slug(text: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in text)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "hypothesis"


def _build_generation_rationale(
    *,
    trigger: str,
    summary: str,
    linked_uncertainties: list[str],
    derived_features: list[str],
    source_signals: list[HypothesisSourceSignal],
    confidence: float,
) -> HypothesisGenerationRationale:
    return HypothesisGenerationRationale(
        trigger=trigger,
        summary=summary,
        linked_uncertainties=_unique_preserve_order(linked_uncertainties),
        derived_features=_unique_preserve_order(derived_features),
        source_signals=source_signals,
        confidence=confidence,
    )


def _linked_uncertainty_ids(
    uncertainties: list[UncertaintyRecord],
    *,
    keywords: list[str],
) -> list[str]:
    ids: list[str] = []
    lowered_keywords = [item.lower() for item in keywords if item]
    for record in uncertainties:
        text = f"{record.question} {record.description}".lower()
        if any(keyword in text for keyword in lowered_keywords):
            ids.append(record.uncertainty_id)
    if not ids and uncertainties:
        ids.append(uncertainties[0].uncertainty_id)
    return ids


def _task_bootstrap_signals(
    task: ScientificTask,
    data_dictionary: DataDictionary,
    uncertainties: list[UncertaintyRecord],
    primary_x: str,
    target: str,
) -> list[HypothesisSourceSignal]:
    signals = [
        HypothesisSourceSignal(
            signal_type="scientific_task",
            source_id=task.task_id,
            source_round=0,
            excerpt=task.payload.research_question.text,
            weight=0.95,
        ),
        HypothesisSourceSignal(
            signal_type="data_dictionary",
            source_id=data_dictionary.dictionary_id,
            source_round=0,
            excerpt=f"variables available: {primary_x} -> {target}",
            weight=0.8,
        ),
    ]
    signals.extend(_uncertainty_signals(uncertainties, keywords=[primary_x, target, "独立", "independent"], weight=0.72))
    return signals


def _competition_signals(
    task: ScientificTask,
    uncertainties: list[UncertaintyRecord],
    competition_feature: str,
    target: str,
) -> list[HypothesisSourceSignal]:
    signals = [
        HypothesisSourceSignal(
            signal_type="scientific_task",
            source_id=task.task_id,
            source_round=0,
            excerpt=f"需要保留 {competition_feature} 对 {target} 的竞争解释",
            weight=0.7,
        )
    ]
    signals.extend(_uncertainty_signals(uncertainties, keywords=[competition_feature, "伴随", "解释", "中介"], weight=0.68))
    return signals


def _mediator_signals(
    task: ScientificTask,
    uncertainties: list[UncertaintyRecord],
    mediator: str,
) -> list[HypothesisSourceSignal]:
    signals = [
        HypothesisSourceSignal(
            signal_type="scientific_task",
            source_id=task.task_id,
            source_round=0,
            excerpt=f"research question 提供 mediator candidate: {mediator}",
            weight=0.82,
        )
    ]
    signals.extend(_uncertainty_signals(uncertainties, keywords=[mediator, "中介", "mediator"], weight=0.75))
    return signals


def _stability_signals(
    task: ScientificTask,
    uncertainties: list[UncertaintyRecord],
) -> list[HypothesisSourceSignal]:
    signals = [
        HypothesisSourceSignal(
            signal_type="scientific_task",
            source_id=task.task_id,
            source_round=0,
            excerpt=f"question context: {task.payload.research_question.text}",
            weight=0.62,
        )
    ]
    signals.extend(_uncertainty_signals(uncertainties, keywords=["稳定", "stability", "滞后", "time", "跨时间"], weight=0.86))
    return signals


def _planner_feature_signals(
    planner_input: ReasoningPlannerInput | None,
    feature: str,
) -> list[HypothesisSourceSignal]:
    if planner_input is None:
        return []
    signals: list[HypothesisSourceSignal] = []
    if planner_input.human_feedback and feature.lower() in planner_input.human_feedback.lower():
        signals.append(
            HypothesisSourceSignal(
                signal_type="human_feedback",
                source_round=planner_input.source_round_id,
                excerpt=planner_input.human_feedback,
                weight=0.9,
            )
        )
    for item in planner_input.recent_human_feedback:
        if feature.lower() in item.content.lower():
            signals.append(
                HypothesisSourceSignal(
                    signal_type="human_feedback_entry",
                    source_id=item.feedback_id,
                    source_round=planner_input.source_round_id,
                    excerpt=item.content,
                    weight=0.88,
                )
            )
    for trace in planner_input.recent_reasoning_traces:
        if feature.lower() in trace.summary.lower():
            signals.append(
                HypothesisSourceSignal(
                    signal_type="reasoning_trace",
                    source_id=trace.trace_id,
                    source_round=planner_input.source_round_id,
                    excerpt=trace.summary,
                    weight=0.76,
                )
            )
    for note in planner_input.planner_guidance:
        if feature.lower() in note.lower():
            signals.append(
                HypothesisSourceSignal(
                    signal_type="planner_guidance",
                    source_round=planner_input.source_round_id,
                    excerpt=note,
                    weight=0.7,
                )
            )
    return signals or [
        HypothesisSourceSignal(
            signal_type="planner_input",
            source_round=planner_input.source_round_id,
            excerpt=f"planner requested focus on {feature}",
            weight=0.6,
        )
    ]


def _stability_refinement_signals(
    planner_input: ReasoningPlannerInput | None,
    uncertainties: list[UncertaintyRecord],
) -> list[HypothesisSourceSignal]:
    signals = _uncertainty_signals(uncertainties, keywords=["稳定", "stability", "滞后", "time", "跨时间"], weight=0.84)
    if planner_input:
        if planner_input.evaluation_summary.stable is False:
            signals.append(
                HypothesisSourceSignal(
                    signal_type="evaluation_summary",
                    source_id=planner_input.source_experiment_id,
                    source_round=planner_input.source_round_id,
                    excerpt="evaluation summary reports unstable result",
                    weight=0.9,
                )
            )
        for trace in planner_input.recent_reasoning_traces:
            if any(token in trace.summary.lower() for token in ("稳定", "stability", "时间", "time")):
                signals.append(
                    HypothesisSourceSignal(
                        signal_type="reasoning_trace",
                        source_id=trace.trace_id,
                        source_round=planner_input.source_round_id,
                        excerpt=trace.summary,
                        weight=0.75,
                    )
                )
    return signals


def _weakened_assessment_signals(
    planner_input: ReasoningPlannerInput | None,
    alternative_feature: str,
) -> list[HypothesisSourceSignal]:
    signals: list[HypothesisSourceSignal] = []
    if planner_input:
        for assessment in planner_input.recent_hypothesis_assessments:
            if assessment.status == "weakened":
                signals.append(
                    HypothesisSourceSignal(
                        signal_type="evaluation_assessment",
                        source_id=assessment.hypothesis_id,
                        source_round=planner_input.source_round_id,
                        excerpt=assessment.reason,
                        weight=0.87,
                    )
                )
        if planner_input.human_feedback and alternative_feature.lower() in planner_input.human_feedback.lower():
            signals.append(
                HypothesisSourceSignal(
                    signal_type="human_feedback",
                    source_round=planner_input.source_round_id,
                    excerpt=planner_input.human_feedback,
                    weight=0.72,
                )
            )
    return signals


def _uncertainty_signals(
    uncertainties: list[UncertaintyRecord],
    *,
    keywords: list[str],
    weight: float,
) -> list[HypothesisSourceSignal]:
    signals: list[HypothesisSourceSignal] = []
    lowered_keywords = [item.lower() for item in keywords if item]
    for record in uncertainties:
        text = f"{record.question} {record.description}".lower()
        if any(keyword in text for keyword in lowered_keywords):
            signals.append(
                HypothesisSourceSignal(
                    signal_type="uncertainty_record",
                    source_id=record.uncertainty_id,
                    source_round=record.created_at_round,
                    excerpt=record.question,
                    weight=weight,
                )
            )
    return signals


def _node_keywords(node: HypothesisNode) -> list[str]:
    rationale = node.generation_rationale
    keywords: list[str] = []
    if rationale:
        keywords.extend(rationale.derived_features)
    keywords.extend(node.statement.replace("，", " ").replace("。", " ").split())
    return [item for item in keywords if item]


def _unique_preserve_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
