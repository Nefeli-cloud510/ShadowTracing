from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.central_controller_llm import CentralControllerLLM
from core.decision_unified import DecisionLayerService
from core.evaluation_unified import evaluate_experiment, export_evaluation_result
from core.experiment_planner_llm import ExperimentPlannerLLM
from core.harness_unified import UnifiedExperimentHarness
from core.hypothesis_proposer_llm import HypothesisProposerLLM
from core.hypothesis_generation import HypothesisGenerationService
from core.llm_gateway import LLMGateway
from core.parallel_reasoning_orchestrator import ParallelReasoningOrchestrator
from core.planner_output_applier import PlannerOutputApplier
from core.planner_unified import PlannerOutputBuilder, ReasoningPlannerInputBuilder
from core.protocol_bridge import ElasticNetDataSourceConfig
from core.rag_service import RAGContextBundle, RAGService
from core.runtime_config import get_llm_model_for_role
from core.scientific_interpreter_llm import ScientificInterpreterLLM
from core.scientific_questioner_llm import ScientificQuestionerLLM
from core.state_repository import UnifiedStateRepository
from core.state_updater import UnifiedStateUpdater
from core.unified_schema import (
    CandidateExperiment,
    DataDictionary,
    DataDictionarySummary,
    DecisionEntry,
    DecisionLog,
    EvaluationResult,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStep,
    HypothesisSnapshot,
    HumanFeedbackEntry,
    PlannerEvaluationSummary,
    PlannerDisagreementUpdateItem,
    PlannerReasoningTraceItem,
    PlannerUncertaintyItem,
    ProcessPhase,
    ProcessState,
    ProcessStep,
    ProtocolRefinementSuggestion,
    ProtocolConstraints,
    RejectedCandidate,
    ReasoningPlannerInput,
    ReasoningPlannerOutput,
    ScientificTask,
    StopHistoryEntry,
    UncertaintyRecord,
)


class CandidateProtocolMapper:
    """Map selected candidate experiments into executable ExperimentProtocol objects."""

    def to_protocol(
        self,
        *,
        task: ScientificTask,
        candidate: CandidateExperiment,
        round_id: int,
        model_name: str = "ElasticNet",
        model_parameters: dict[str, Any] | None = None,
        protocol_refinements: list[ProtocolRefinementSuggestion] | None = None,
    ) -> ExperimentProtocol:
        parameters = {
            "window_size": 3,
            "alpha": 0.3,
            "l1_ratio": 0.5,
            "use_lag_feature": bool(candidate.design.lags),
            "max_lag_day": max((max(values) for values in candidate.design.lags.values()), default=0),
            "random_state": 42,
            "test_split_ratio": 0.2,
        }
        if model_parameters:
            parameters.update(model_parameters)
        refinement_notes: list[str] = []
        refinement_steps: list[ExperimentStep] = []
        if protocol_refinements:
            for refinement in protocol_refinements:
                parameters.update(refinement.suggested_model_parameters)
                refinement_notes.append(f"planner_refinement:{refinement.refinement_type}")
                refinement_notes.extend(refinement.protocol_notes)
                refinement_steps.extend(step.model_copy(deep=True) for step in refinement.suggested_steps)

        base_steps = [
            ExperimentStep(step=1, action="data_quality_check"),
            ExperimentStep(step=2, action="run_model", parameters={"features": "control", "label": "baseline"}),
            ExperimentStep(step=3, action="run_model", parameters={"features": "treatment", "label": "treatment"}),
            ExperimentStep(
                step=4,
                action="comparison",
                parameters={"baseline_label": "baseline", "treatment_label": "treatment"},
            ),
        ]
        disagreement_steps = _build_disagreement_steps(candidate)
        steps = _renumber_steps(refinement_steps + disagreement_steps + base_steps)
        protocol_notes = [
            f"mapped_from_candidate:{candidate.experiment_id}",
            candidate.distinguishing_insight or "no distinguishing insight provided",
        ]
        protocol_notes.extend(_disagreement_notes(candidate))

        return ExperimentProtocol(
            experiment_id=candidate.experiment_id,
            round_id=round_id,
            task_id=task.task_id,
            target=candidate.design.target,
            scientific_objective=candidate.scientific_question or candidate.purpose,
            forecast_horizon_days=max((max(values) for values in candidate.design.lags.values()), default=3),
            features=candidate.design,
            model={
                "name": model_name,
                "parameters": parameters,
            },
            tested_hypotheses=candidate.tested_hypotheses,
            target_uncertainties=candidate.related_uncertainties,
            disagreement_context=candidate.disagreement_context,
            hypothesis_source_context=candidate.hypothesis_source_context,
            hypothesis_predictions=candidate.hypothesis_predictions,
            budget=task.payload.constraints.resource_budget,
            steps=steps,
            constraints=ProtocolConstraints(
                no_future_information=task.payload.constraints.no_future_information,
                target_immutable=True,
            ),
            source_candidate_id=candidate.experiment_id,
            requires_human_review=candidate.requires_human_review,
            notes=protocol_notes + refinement_notes,
        )


class HumanControlService:
    """Persist human-in-the-loop approvals, pauses, and protocol generation."""

    def __init__(
        self,
        repository: UnifiedStateRepository,
        *,
        project_root: Path | None = None,
        mapper: CandidateProtocolMapper | None = None,
        hypothesis_generator: HypothesisGenerationService | None = None,
        run_shap: bool = False,
        planner_mode: str = "programmatic",
        planner_output_builder: PlannerOutputBuilder | None = None,
        scientific_interpreter: ScientificInterpreterLLM | None = None,
        rag_service: RAGService | None = None,
        hypothesis_proposer: HypothesisProposerLLM | None = None,
        scientific_questioner: ScientificQuestionerLLM | None = None,
        experiment_planner: ExperimentPlannerLLM | None = None,
        parallel_reasoning_orchestrator: ParallelReasoningOrchestrator | None = None,
    ) -> None:
        self.repository = repository
        self.project_root = project_root or repository.project_root
        self.config_dir = self.project_root / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.protocol_path = self.config_dir / "latest_protocol.json"
        self.mapper = mapper or CandidateProtocolMapper()
        self.hypothesis_generator = hypothesis_generator or HypothesisGenerationService()
        self.run_shap = run_shap
        self.planner_mode = planner_mode
        if planner_output_builder is not None:
            self.planner_output_builder = planner_output_builder
        elif planner_mode == "llm":
            self.planner_output_builder = PlannerOutputBuilder(
                mode="llm",
                central_controller=CentralControllerLLM(
                    gateway=LLMGateway(model=get_llm_model_for_role("central_controller"))
                ),
            )
        else:
            self.planner_output_builder = PlannerOutputBuilder(mode=planner_mode)
        self.scientific_interpreter = scientific_interpreter or ScientificInterpreterLLM(
            gateway=LLMGateway(model=get_llm_model_for_role("scientific_interpreter"))
        )
        self.rag_service = rag_service or RAGService(project_root=self.project_root)
        self.hypothesis_proposer = hypothesis_proposer or HypothesisProposerLLM(
            gateway=LLMGateway(model=get_llm_model_for_role("hypothesis_proposer"))
        )
        self.scientific_questioner = scientific_questioner or ScientificQuestionerLLM(
            gateway=LLMGateway(model=get_llm_model_for_role("scientific_questioner"))
        )
        self.experiment_planner = experiment_planner or ExperimentPlannerLLM(
            gateway=LLMGateway(model=get_llm_model_for_role("experiment_planner"))
        )
        self.parallel_reasoning_orchestrator = parallel_reasoning_orchestrator or ParallelReasoningOrchestrator(
            hypothesis_proposer=self.hypothesis_proposer,
            scientific_questioner=self.scientific_questioner,
        )

    def request_experiment_selection_review(self) -> dict[str, Any]:
        candidate_set = self.repository.load_candidate_experiments()
        top_candidate = candidate_set.top_candidate()
        process_state = self.repository.load_process_state()
        process_state = self._mark_selection_waiting(process_state)
        self.repository.save_process_state(process_state)
        decision_log = self.repository.load_decision_log()

        if top_candidate is None:
            decision_log.decisions.append(
                DecisionEntry(
                    decision_id=self._next_decision_id(decision_log),
                    timestamp=datetime.now(),
                    round_id=candidate_set.round,
                    phase="experiment_planning",
                    step="experiment_selection",
                    decision_type="experiment_selection_requested",
                    made_by="system",
                    summary="系统尝试发起候选实验审批，但当前没有可审批候选。",
                    details={"status": "no_candidate"},
                )
            )
            self.repository.save_decision_log(decision_log)
            return {
                "status": "no_candidate",
                "message": "当前没有可审批的候选实验。",
            }

        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=candidate_set.round,
                phase="experiment_planning",
                step="experiment_selection",
                decision_type="experiment_selection_requested",
                made_by="system",
                summary=f"系统请求 human_pi 审批候选实验 {top_candidate.experiment_id}",
                details={
                    "candidate_id": top_candidate.experiment_id,
                    "utility_score": top_candidate.utility_score,
                },
            )
        )
        self.repository.save_decision_log(decision_log)
        return {
            "status": "awaiting_human_review",
            "recommended_candidate": top_candidate.model_dump(mode="json", exclude_none=True),
            "current_phase": process_state.current_phase,
            "current_step": process_state.current_step,
            "approval_options": ["批准并继续", "修改参数", "拒绝并重选", "暂停实验"],
        }

    def approve_candidate(
        self,
        *,
        candidate_id: str | None = None,
        human_notes: str | None = None,
        auto_continue: bool | None = None,
        model_parameters: dict[str, Any] | None = None,
    ) -> ExperimentProtocol:
        task = self.repository.load_task()
        candidate_set = self.repository.load_candidate_experiments()
        candidate = self._select_candidate(candidate_set, candidate_id)
        protocol_refinements = self._build_protocol_refinements(
            task=task,
            candidate=candidate,
        )
        protocol = self.mapper.to_protocol(
            task=task,
            candidate=candidate,
            round_id=candidate_set.round,
            model_parameters=model_parameters,
            protocol_refinements=protocol_refinements,
        )
        self._save_protocol(protocol)

        process_state = self.repository.load_process_state()
        process_state = self._mark_protocol_generated(process_state, auto_continue=auto_continue)
        self.repository.save_process_state(process_state)

        decision_log = self.repository.load_decision_log()
        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=protocol.round_id,
                phase="experiment_planning",
                step="experiment_selection",
                decision_type="experiment_approved",
                made_by="human_pi",
                summary=f"用户批准实验 {candidate.experiment_id}",
                details={
                    "candidate_id": candidate.experiment_id,
                    "utility_score": candidate.utility_score,
                    "notes": human_notes,
                    "auto_continue": auto_continue,
                },
            )
        )
        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=protocol.round_id,
                phase="experiment_planning",
                step="protocol_generation",
                decision_type="protocol_generated",
                made_by="system",
                summary=f"已为 {candidate.experiment_id} 生成执行协议",
                details={
                    "protocol_path": self.repository.relativize(self.protocol_path),
                    "scientific_objective": protocol.scientific_objective,
                    "refinement_types": [item.refinement_type for item in protocol_refinements or []],
                },
            )
        )
        self.repository.save_decision_log(decision_log)
        return protocol

    def reject_candidate(
        self,
        *,
        candidate_id: str | None = None,
        reason: str,
    ) -> dict[str, Any]:
        candidate_set = self.repository.load_candidate_experiments()
        candidate = self._select_candidate(candidate_set, candidate_id)
        candidate_set.candidates = [
            item for item in candidate_set.candidates if item.experiment_id != candidate.experiment_id
        ]
        candidate_set.rejected_candidates.append(
            RejectedCandidate(
                experiment_id=candidate.experiment_id,
                reason=reason,
                similar_to=candidate.experiment_id,
            )
        )
        candidate_set.current_count = len(candidate_set.candidates)
        if candidate_set.current_count < candidate_set.minimum_required:
            candidate_set.note = "候选实验被人工拒绝后数量不足，建议重新生成或补充候选实验。"
        self.repository.save_candidate_experiments(candidate_set)

        process_state = self.repository.load_process_state()
        process_state = self._mark_reselection_waiting(process_state)
        self.repository.save_process_state(process_state)

        decision_log = self.repository.load_decision_log()
        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=candidate_set.round,
                phase="experiment_planning",
                step="experiment_selection",
                decision_type="experiment_rejected",
                made_by="human_pi",
                summary=f"用户拒绝实验 {candidate.experiment_id}",
                details={"reason": reason},
            )
        )
        self.repository.save_decision_log(decision_log)
        return {
            "status": "rejected",
            "candidate_id": candidate.experiment_id,
            "reason": reason,
            "remaining_candidates": candidate_set.current_count,
        }

    def approve_and_execute_candidate(
        self,
        *,
        candidate_id: str | None = None,
        human_notes: str | None = None,
        auto_continue: bool | None = None,
        model_parameters: dict[str, Any] | None = None,
        remaining_uncertainties: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        protocol = self.approve_candidate(
            candidate_id=candidate_id,
            human_notes=human_notes,
            auto_continue=auto_continue,
            model_parameters=model_parameters,
        )
        task = self.repository.load_task()
        harness = UnifiedExperimentHarness(
            data_source=self._build_data_source_config(task),
            project_root=self.project_root,
            run_shap=self.run_shap,
        )
        result = harness.run(protocol)
        unresolved = remaining_uncertainties or self._remaining_uncertainties_for_review(protocol)
        evaluation = evaluate_experiment(
            result,
            protocol=protocol,
            remaining_uncertainties=unresolved,
        )
        interpreter_enhancements = self._build_interpreter_enhancements(
            protocol=protocol,
            evaluation=evaluation,
        )
        round_dir = self.project_root / "results" / f"round_{protocol.round_id:02d}"
        evaluation_path = round_dir / "evaluation_unified.json"
        export_evaluation_result(evaluation, evaluation_path)

        updater = UnifiedStateUpdater(self.repository)
        updater.apply_evaluation(
            protocol=protocol,
            result=result,
            evaluation=evaluation,
            interpretation_enhancements=interpreter_enhancements,
            protocol_path=self.repository.relativize(self.protocol_path),
            result_path=f"results/round_{protocol.round_id:02d}/result_unified.json",
            evaluation_path=self.repository.relativize(evaluation_path),
        )
        self._log_scientific_interpreter_applied(
            round_id=protocol.round_id,
            experiment_id=protocol.experiment_id,
            interpretation_enhancements=interpreter_enhancements,
        )
        review_payload = self.request_round_review(
            round_id=protocol.round_id,
            experiment_id=protocol.experiment_id,
            evaluation_summary=self._build_evaluation_summary(evaluation),
            hypothesis_assessments=[
                item.model_dump(mode="json", exclude_none=True)
                for item in evaluation.scientific.hypothesis_assessments
            ],
            disagreement_updates=[
                item.model_dump(mode="json", exclude_none=True)
                for item in evaluation.scientific.disagreement_updates
            ],
            reasoning_traces=self._recent_reasoning_traces_for_experiment(protocol.experiment_id),
        )
        return {
            "protocol": protocol,
            "result": result,
            "evaluation": evaluation,
            "review": review_payload,
        }

    def request_stop(self, *, phase: str, reason: str, pause: bool = True) -> None:
        process_state = self.repository.load_process_state()
        process_state.user_requests.stop_requested = True
        process_state.user_requests.stop_at_phase = phase
        process_state.user_requests.pause_reason = reason
        process_state.current_stage = "paused" if pause else "stopped"
        process_state.current_phase = phase
        process_state.current_step = "manual_control"
        self.repository.save_process_state(process_state)

        decision_log = self.repository.load_decision_log()
        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=process_state.current_round,
                phase=phase,
                step="manual_control",
                decision_type="pause_requested" if pause else "stop_requested",
                made_by="human_pi",
                summary="用户请求暂停实验" if pause else "用户请求停止实验",
                details={"reason": reason},
            )
        )
        decision_log.stop_history.append(
            StopHistoryEntry(
                stop_id=f"S{len(decision_log.stop_history) + 1:03d}",
                timestamp=datetime.now(),
                type="pause" if pause else "stop",
                phase=phase,
                reason=reason,
            )
        )
        self.repository.save_decision_log(decision_log)

    def request_round_review(
        self,
        *,
        round_id: int,
        experiment_id: str | None = None,
        evaluation_summary: dict[str, Any] | None = None,
        hypothesis_assessments: list[dict[str, Any]] | None = None,
        disagreement_updates: list[dict[str, Any]] | None = None,
        reasoning_traces: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        process_state = self.repository.load_process_state()
        process_state.current_round = max(process_state.current_round, round_id)
        process_state.current_phase = "decision_making"
        process_state.current_step = "round_review"
        process_state.current_stage = "awaiting_round_decision"
        process_state.progress_percentage = 85
        process_state.phases["decision_making"] = ProcessPhase(
            status="in_progress",
            steps={
                "round_review": ProcessStep(
                    name="round_review",
                    status="pending",
                    requires_user_approval=True,
                    notes="等待 human_pi 决定是否进入下一轮。",
                )
            },
        )
        self.repository.save_process_state(process_state)

        decision_log = self.repository.load_decision_log()
        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=round_id,
                phase="decision_making",
                step="round_review",
                decision_type="round_review_requested",
                made_by="system",
                summary=f"系统请求 human_pi 对 round {round_id} 作出下一步决策",
                details={
                    "experiment_id": experiment_id,
                    "evaluation_summary": evaluation_summary or {},
                    "hypothesis_assessments": hypothesis_assessments or [],
                    "disagreement_updates": disagreement_updates or [],
                    "reasoning_traces": reasoning_traces or [],
                },
            )
        )
        self.repository.save_decision_log(decision_log)
        return {
            "status": "awaiting_round_decision",
            "round_id": round_id,
            "experiment_id": experiment_id,
            "options": ["进入下一轮", "进入下一轮并调整方向", "停止实验"],
            "evaluation_summary": evaluation_summary or {},
            "hypothesis_assessments": hypothesis_assessments or [],
            "disagreement_updates": disagreement_updates or [],
            "reasoning_traces": reasoning_traces or [],
        }

    def record_round_decision(
        self,
        *,
        round_id: int,
        decision: str,
        summary: str | None = None,
        human_feedback: str | None = None,
        auto_continue: bool | None = None,
        data_dictionary: DataDictionary | None = None,
    ) -> dict[str, Any]:
        decision_type_map = {
            "continue": "continue_next_round",
            "adjust": "round_adjusted",
            "stop": "terminate_workflow",
        }
        if decision not in decision_type_map:
            raise ValueError("decision must be one of: continue, adjust, stop")

        process_state = self.repository.load_process_state()
        if auto_continue is not None:
            process_state.user_settings.auto_continue = auto_continue
        process_state.current_round = max(process_state.current_round, round_id)
        process_state.current_phase = "next_round" if decision != "stop" else "decision_making"
        process_state.current_step = "handoff" if decision != "stop" else "workflow_terminated"
        process_state.current_stage = "next_round_ready" if decision != "stop" else "workflow_terminated"
        process_state.progress_percentage = 100 if decision == "stop" else 90
        process_state.phases["decision_making"] = ProcessPhase(
            status="completed",
            completed_at=datetime.now(),
            steps={
                "round_review": ProcessStep(
                    name="round_review",
                    status="completed",
                    requires_user_approval=True,
                )
            },
        )
        process_state.phases["next_round"] = ProcessPhase(
            status="pending" if decision != "stop" else "skipped",
            notes="waiting for next-round planning" if decision != "stop" else "workflow terminated by human_pi",
        )
        self.repository.save_process_state(process_state)

        decision_log = self.repository.load_decision_log()
        review_context = self._latest_round_review_context(decision_log, round_id)
        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=round_id,
                phase="decision_making",
                step="round_review",
                decision_type=decision_type_map[decision],
                made_by="human_pi",
                summary=summary or self._default_round_summary(round_id, decision),
                details={
                    "human_feedback": human_feedback,
                    "auto_continue": process_state.user_settings.auto_continue,
                },
            )
        )
        if human_feedback:
            decision_log.human_feedback.append(
                HumanFeedbackEntry(
                    feedback_id=f"F{len(decision_log.human_feedback) + 1:03d}",
                    timestamp=datetime.now(),
                    phase="decision_making",
                    round_number=round_id,
                    feedback_type="改进建议" if decision == "adjust" else "轮次备注",
                    content=human_feedback,
                    implemented_in_round=round_id + 1 if decision != "stop" else None,
                    status="recorded",
                    related_experiment_id=review_context.get("experiment_id"),
                    linked_reasoning_trace_ids=review_context.get("reasoning_trace_ids", []),
                    context_summary=review_context.get("context_summary"),
                )
            )
        self.repository.save_decision_log(decision_log)

        payload: dict[str, Any] = {
            "status": "recorded",
            "decision_type": decision_type_map[decision],
            "round_id": round_id,
        }
        if decision != "stop":
            payload.update(
                self._resume_next_round_planning(
                    round_id=round_id,
                    human_feedback=human_feedback if decision == "adjust" else None,
                    data_dictionary=data_dictionary,
                )
            )
        return payload

    def _save_protocol(self, protocol: ExperimentProtocol) -> None:
        self.protocol_path.write_text(
            json.dumps(protocol.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_data_source_config(self, task: ScientificTask) -> ElasticNetDataSourceConfig:
        data_sources = task.payload.data_sources
        omni = data_sources.get("omni")
        lhaaso = data_sources.get("lhaaso")
        if not omni or not lhaaso:
            raise KeyError("task.payload.data_sources 必须同时包含 omni 和 lhaaso 配置")

        time_column = omni.get("time_column") or lhaaso.get("time_column") or "TIME"
        target_column = omni.get("target_column") or task.payload.research_question.target
        return ElasticNetDataSourceConfig(
            omni_file_path=self._resolve_project_path(omni["path"]),
            lhaaso_file_path=self._resolve_project_path(lhaaso["path"]),
            time_column=time_column,
            target_column=target_column,
        )

    def _resolve_project_path(self, path_value: str) -> Path:
        candidate = Path(path_value)
        return candidate if candidate.is_absolute() else self.project_root / candidate

    def _remaining_uncertainties_for_review(self, protocol: ExperimentProtocol) -> list[dict[str, Any]]:
        state = self.repository.load_uncertainties()
        unresolved: list[dict[str, Any]] = []
        for record in state.records:
            if record.status in {"resolved", "deprecated"}:
                continue
            unresolved.append(
                {
                    "uncertainty_id": record.uncertainty_id,
                    "question": record.question,
                    "priority": record.priority,
                }
            )
            if len(unresolved) >= 3:
                break
        return unresolved

    @staticmethod
    def _build_evaluation_summary(evaluation: EvaluationResult) -> dict[str, Any]:
        metrics = evaluation.metrics
        return {
            "experiment_id": metrics.experiment_id,
            "round_id": metrics.round_id,
            "baseline_rmse": metrics.baseline_rmse,
            "treatment_rmse": metrics.treatment_rmse,
            "baseline_pearson_r": metrics.baseline_pearson_r,
            "treatment_pearson_r": metrics.treatment_pearson_r,
            "delta_pearson_r": metrics.delta.pearson_r,
            "delta_rmse": metrics.delta.rmse,
            "pg_actual_signed": metrics.pg_actual_signed,
            "pg_actual_clipped": metrics.pg_actual_clipped,
            "remaining_uncertainties": evaluation.scientific.evidence_summary.remaining_uncertainties,
            "key_findings": [
                item.claim for item in evaluation.scientific.evidence_summary.new_evidence_for
            ][:3],
            "robustness_recommendation": evaluation.robustness.recommendation,
            "stable": evaluation.robustness.overall.stable,
        }

    def _resume_next_round_planning(
        self,
        *,
        round_id: int,
        human_feedback: str | None,
        data_dictionary: DataDictionary | None,
    ) -> dict[str, Any]:
        if data_dictionary is None:
            return {
                "planning_status": "awaiting_data_dictionary",
                "message": "需要提供 DataDictionary 后才能自动生成下一轮候选实验。",
            }

        task = self.repository.load_task()
        uncertainties = self.repository.load_uncertainties()
        uncertainties.current_round = max(uncertainties.current_round, round_id)
        self.repository.save_uncertainties(uncertainties)

        planner_input_builder = ReasoningPlannerInputBuilder(self.repository)
        planner_input = planner_input_builder.build(
            data_dictionary=data_dictionary,
            source_round_id=round_id,
            human_feedback=human_feedback,
        )
        if self.planner_mode == "llm":
            planner_input, uncertainties = self._augment_next_round_context_with_llm_services(
                planner_input=planner_input,
                uncertainties=uncertainties,
            )
        generation_result = self.hypothesis_generator.build_tree(
            task=task,
            data_dictionary=data_dictionary,
            uncertainties=uncertainties,
            planner_input=planner_input,
            existing_tree=self.repository.load_hypothesis_tree(),
            current_round=round_id + 1,
        )
        uncertainties.records = list(generation_result.updated_uncertainties)
        self.repository.save_uncertainties(uncertainties)
        if generation_result.generated_node_ids:
            self.repository.save_hypothesis_tree(generation_result.tree)
            self._log_hypothesis_generation(
                round_id=round_id,
                next_round_id=round_id + 1,
                generation_result=generation_result,
                mode=generation_result.mode,
            )
            planner_input = planner_input_builder.build(
                data_dictionary=data_dictionary,
                source_round_id=round_id,
                human_feedback=human_feedback,
            )
            if self.planner_mode == "llm":
                planner_input, uncertainties = self._augment_next_round_context_with_llm_services(
                    planner_input=planner_input,
                    uncertainties=uncertainties,
                )
                self.repository.save_uncertainties(uncertainties)
        self.repository.save_planner_input(planner_input)
        self._log_planner_input_prepared(planner_input)

        process_state = self.repository.load_process_state()
        process_state.current_round = max(process_state.current_round, round_id)
        process_state.current_phase = "next_round"
        process_state.current_step = "planner_input_prepared"
        process_state.current_stage = "planner_input_ready"
        process_state.progress_percentage = 92
        process_state.phases["next_round"] = ProcessPhase(
            status="in_progress",
            started_at=datetime.now(),
            notes="planner input prepared for next-round reasoning/planning",
            steps={
                "planner_input_prepared": ProcessStep(
                    name="planner_input_prepared",
                    status="completed",
                    requires_user_approval=False,
                    notes=human_feedback or "reuse current planning policy",
                ),
                "candidate_generation": ProcessStep(
                    name="candidate_generation",
                    status="in_progress",
                    requires_user_approval=False,
                    notes=f"{self.planner_mode} candidate generation is consuming planner_input",
                )
            },
        )
        self.repository.save_process_state(process_state)

        plan = DecisionLayerService(self.repository).build_candidate_plan(
            task=task,
            data_dictionary=data_dictionary,
            planner_input=planner_input,
        )
        planner_output = self.planner_output_builder.build(
            planner_input=planner_input,
            candidate_plan=plan,
        )
        self.repository.save_planner_output(planner_output)
        self._log_planner_output_generated(planner_output)
        applied_output = PlannerOutputApplier(self.repository).apply(planner_output)
        review = self.request_experiment_selection_review()
        return {
            "planning_status": "candidate_plan_rebuilt",
            "hypothesis_generation": {
                "mode": generation_result.mode,
                "generated_node_ids": list(generation_result.generated_node_ids),
            },
            "planner_input": planner_input,
            "planner_output": planner_output,
            "applied_output": applied_output,
            "candidate_plan": plan,
            "next_review": review,
        }

    def _select_candidate(self, candidate_set, candidate_id: str | None) -> CandidateExperiment:
        if candidate_id is None:
            top_candidate = candidate_set.top_candidate()
            if top_candidate is None:
                raise ValueError("当前没有可审批的候选实验。")
            return top_candidate

        for candidate in candidate_set.candidates:
            if candidate.experiment_id == candidate_id:
                return candidate
        raise KeyError(f"找不到候选实验: {candidate_id}")

    def _mark_selection_waiting(self, process_state: ProcessState) -> ProcessState:
        now = datetime.now()
        process_state.current_phase = "experiment_planning"
        process_state.current_step = "step_4"
        process_state.current_stage = "awaiting_human_approval"
        process_state.progress_percentage = 45
        planning = process_state.phases.get(
            "experiment_planning",
            ProcessPhase(status="in_progress", started_at=now),
        )
        planning.status = "in_progress"
        planning.started_at = planning.started_at or now
        planning.steps = {
            "step_1": ProcessStep(name="识别关键不确定性", status="completed"),
            "step_2": ProcessStep(name="生成候选实验", status="completed"),
            "step_3": ProcessStep(name="计算综合价值", status="completed"),
            "step_4": ProcessStep(name="选择E*", status="pending", requires_user_approval=True),
            "step_5": ProcessStep(name="生成实验协议", status="pending"),
        }
        process_state.phases["experiment_planning"] = planning
        return process_state

    def _mark_reselection_waiting(self, process_state: ProcessState) -> ProcessState:
        process_state = self._mark_selection_waiting(process_state)
        process_state.current_stage = "candidate_rejected"
        planning = process_state.phases["experiment_planning"]
        planning.steps["step_4"].notes = "上一候选已被 human_pi 拒绝，等待重新选择。"
        process_state.phases["experiment_planning"] = planning
        return process_state

    def _mark_protocol_generated(self, process_state: ProcessState, auto_continue: bool | None) -> ProcessState:
        now = datetime.now()
        process_state.current_phase = "experiment_planning"
        process_state.current_step = "step_5"
        process_state.current_stage = "protocol_ready"
        process_state.progress_percentage = 55
        if auto_continue is not None:
            process_state.user_settings.auto_continue = auto_continue
        planning = process_state.phases.get(
            "experiment_planning",
            ProcessPhase(status="in_progress", started_at=now),
        )
        planning.status = "completed" if process_state.user_settings.auto_continue else "in_progress"
        planning.steps = {
            "step_1": ProcessStep(name="识别关键不确定性", status="completed"),
            "step_2": ProcessStep(name="生成候选实验", status="completed"),
            "step_3": ProcessStep(name="计算综合价值", status="completed"),
            "step_4": ProcessStep(name="选择E*", status="completed", requires_user_approval=True),
            "step_5": ProcessStep(name="生成实验协议", status="completed"),
        }
        planning.completed_at = now if planning.status == "completed" else None
        process_state.phases["experiment_planning"] = planning
        process_state.phases["experiment_execution"] = ProcessPhase(
            status="pending",
            steps={},
            notes="waiting for harness execution",
        )
        return process_state

    @staticmethod
    def _next_decision_id(log: DecisionLog) -> str:
        return f"D{len(log.decisions) + 1:03d}"

    @staticmethod
    def _default_round_summary(round_id: int, decision: str) -> str:
        mapping = {
            "continue": f"用户批准 round {round_id} 进入下一轮",
            "adjust": f"用户批准 round {round_id} 进入下一轮，但要求调整后续方向",
            "stop": f"用户在 round {round_id} 结束后停止工作流",
        }
        return mapping[decision]

    def _log_planner_input_prepared(self, planner_input: ReasoningPlannerInput) -> None:
        decision_log = self.repository.load_decision_log()
        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=planner_input.source_round_id,
                phase="next_round",
                step="planner_input_prepared",
                decision_type="planner_input_prepared",
                made_by="system",
                summary=f"已为 round {planner_input.next_round_id} 生成统一 planner input",
                details={
                    "planner_input_path": self.repository.relativize(self.repository.paths.planner_input),
                    "source_experiment_id": planner_input.source_experiment_id,
                    "human_feedback": planner_input.human_feedback,
                    "planner_guidance": planner_input.planner_guidance[:8],
                },
            )
        )
        self.repository.save_decision_log(decision_log)

    def _log_planner_output_generated(self, planner_output: ReasoningPlannerOutput) -> None:
        decision_log = self.repository.load_decision_log()
        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=planner_output.source_round_id,
                phase="next_round",
                step="planner_output_generated",
                decision_type="planner_output_generated",
                made_by="system",
                summary=f"已为 round {planner_output.next_round_id} 生成统一 planner output",
                details={
                    "planner_output_path": self.repository.relativize(self.repository.paths.planner_output),
                    "planner_mode": planner_output.planner_mode,
                    "candidate_supplements": len(planner_output.candidate_supplements),
                    "protocol_refinements": len(planner_output.protocol_refinements),
                },
            )
        )
        self.repository.save_decision_log(decision_log)

    def _log_scientific_interpreter_applied(
        self,
        *,
        round_id: int,
        experiment_id: str,
        interpretation_enhancements: list,
    ) -> None:
        if not interpretation_enhancements:
            return
        decision_log = self.repository.load_decision_log()
        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=round_id,
                phase="result_analysis",
                step="scientific_interpreter",
                decision_type="scientific_interpreter_applied",
                made_by="system",
                summary=f"科学解释者已为 {experiment_id} 生成解释增强",
                details={
                    "experiment_id": experiment_id,
                    "enhancement_count": len(interpretation_enhancements),
                    "enhancement_ids": [item.enhancement_id for item in interpretation_enhancements],
                },
            )
        )
        self.repository.save_decision_log(decision_log)

    def _build_interpreter_enhancements(
        self,
        *,
        protocol: ExperimentProtocol,
        evaluation: EvaluationResult,
    ) -> list:
        if self.planner_mode != "llm":
            return []
        planner_input = self._build_interpreter_input(protocol=protocol, evaluation=evaluation)
        candidate_plan = self.repository.load_candidate_experiments()
        return self.scientific_interpreter.build_interpretations(
            planner_input=planner_input,
            candidate_plan=candidate_plan,
        )

    def _build_interpreter_input(
        self,
        *,
        protocol: ExperimentProtocol,
        evaluation: EvaluationResult,
    ) -> ReasoningPlannerInput:
        task = self.repository.load_task()
        tree = self.repository.load_hypothesis_tree()
        uncertainties = self.repository.load_uncertainties()
        time_column = next(
            (
                config.get("time_column")
                for config in task.payload.data_sources.values()
                if isinstance(config, dict) and config.get("time_column")
            ),
            "TIME",
        )
        return ReasoningPlannerInput(
            task_id=task.task_id,
            source_round_id=protocol.round_id,
            next_round_id=protocol.round_id,
            source_experiment_id=protocol.experiment_id,
            scientific_question=task.payload.research_question.text,
            target=protocol.target,
            evaluation_summary=self._build_runtime_evaluation_summary(protocol, evaluation),
            unresolved_uncertainties=[
                PlannerUncertaintyItem(
                    uncertainty_id=record.uncertainty_id,
                    question=record.question,
                    priority=record.priority,
                    priority_score=None,
                    status=record.status,
                    resolution_status=record.resolution_status,
                    related_hypotheses=record.related_hypotheses,
                )
                for record in uncertainties.records
                if record.status not in {"resolved", "deprecated"}
            ][:5],
            active_hypotheses=[
                HypothesisSnapshot(
                    hypothesis_id=node.hypothesis_id,
                    statement=node.statement,
                    status=node.status,
                    support_score=node.support_score,
                )
                for node in sorted(
                    [
                        item
                        for item in tree.nodes
                        if item.status in {"active", "observing", "converged"}
                    ],
                    key=lambda item: item.support_score,
                    reverse=True,
                )[:5]
            ],
            recent_hypothesis_assessments=evaluation.scientific.hypothesis_assessments,
            recent_disagreement_updates=[
                PlannerDisagreementUpdateItem(
                    uncertainty_id=item.uncertainty_id,
                    compared_hypotheses=item.compared_hypotheses,
                    narrowed=item.narrowed,
                    resolution_status=item.resolution_status,
                    leading_hypothesis_id=item.leading_hypothesis_id,
                    unresolved_hypotheses=item.unresolved_hypotheses,
                    support_span_before=item.support_span_before,
                    support_span_after=item.support_span_after,
                    summary=item.summary,
                )
                for item in evaluation.scientific.disagreement_updates
            ],
            recent_reasoning_traces=[],
            recent_human_feedback=[],
            data_dictionary_summary=DataDictionarySummary(
                dictionary_id="runtime_inferred",
                dataset_name=task.task_id,
                time_column=time_column,
                target_candidates=[protocol.target],
                feature_candidates=list(dict.fromkeys(protocol.features.control + protocol.features.treatment)),
            ),
            planning_constraints={
                "no_future_information": task.payload.constraints.no_future_information,
                "validation_feedback_allowed": task.payload.constraints.validation_feedback_allowed,
                "final_test_blind": task.payload.constraints.final_test_blind,
            },
            planner_guidance=[
                f"robustness:{evaluation.robustness.recommendation}",
                *[
                    item.get("question") or item.get("description")
                    for item in evaluation.scientific.evidence_summary.remaining_uncertainties[:2]
                    if isinstance(item, dict)
                ],
            ],
        )

    @staticmethod
    def _build_runtime_evaluation_summary(
        protocol: ExperimentProtocol,
        evaluation: EvaluationResult,
    ) -> PlannerEvaluationSummary:
        return PlannerEvaluationSummary(
            experiment_id=protocol.experiment_id,
            round_id=protocol.round_id,
            baseline_rmse=evaluation.metrics.baseline_rmse,
            treatment_rmse=evaluation.metrics.treatment_rmse,
            baseline_pearson_r=evaluation.metrics.baseline_pearson_r,
            treatment_pearson_r=evaluation.metrics.treatment_pearson_r,
            delta_pearson_r=evaluation.metrics.delta.pearson_r,
            delta_rmse=evaluation.metrics.delta.rmse,
            pg_actual_signed=evaluation.metrics.pg_actual_signed,
            pg_actual_clipped=evaluation.metrics.pg_actual_clipped,
            key_findings=(
                [item.claim for item in evaluation.scientific.evidence_summary.new_evidence_for]
                + [item.claim for item in evaluation.scientific.evidence_summary.new_evidence_against]
            )[:3],
            robustness_recommendation=evaluation.robustness.recommendation,
            stable=evaluation.robustness.overall.stable,
        )

    def _augment_next_round_context_with_llm_services(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        uncertainties,
    ) -> tuple[ReasoningPlannerInput, object]:
        rag_context = self.rag_service.build_context_bundle(planner_input)
        planner_input.planner_guidance.extend(
            note for note in rag_context.guidance_notes() if note not in planner_input.planner_guidance
        )
        planner_input.recent_reasoning_traces.extend(
            self._rag_context_to_traces(rag_context, planner_input.source_round_id)
        )

        reasoning_bundle = self.parallel_reasoning_orchestrator.run(
            planner_input=planner_input,
            rag_context=rag_context,
        )
        proposer_output = reasoning_bundle.proposer
        planner_input.planner_guidance.extend(
            note for note in proposer_output.guidance_notes if note not in planner_input.planner_guidance
        )
        planner_input.recent_reasoning_traces.extend(
            self._notes_to_traces(
                notes=proposer_output.proposal_summaries,
                round_id=planner_input.source_round_id,
                stage="hypothesis_proposer",
                prefix="HP",
            )
        )

        questioner_output = reasoning_bundle.questioner
        planner_input.planner_guidance.extend(
            note for note in questioner_output.guidance_notes if note not in planner_input.planner_guidance
        )
        planner_input.recent_reasoning_traces.extend(
            self._notes_to_traces(
                notes=questioner_output.challenge_points,
                round_id=planner_input.source_round_id,
                stage="scientific_questioner",
                prefix="SQ",
            )
        )
        uncertainties = self._merge_questioner_uncertainties(
            uncertainties=uncertainties,
            planner_input=planner_input,
            proposed=questioner_output.proposed_uncertainties,
        )
        planner_input.recent_reasoning_traces = planner_input.recent_reasoning_traces[-10:]
        return planner_input, uncertainties

    @staticmethod
    def _rag_context_to_traces(rag_context: RAGContextBundle, round_id: int) -> list[PlannerReasoningTraceItem]:
        traces: list[PlannerReasoningTraceItem] = []
        for index, item in enumerate(rag_context.project_evidence[:2], start=1):
            traces.append(
                PlannerReasoningTraceItem(
                    trace_id=f"RAGP{index:03d}",
                    stage="rag_project",
                    summary=item.excerpt,
                )
            )
        for index, item in enumerate(rag_context.literature_evidence[:2], start=1):
            traces.append(
                PlannerReasoningTraceItem(
                    trace_id=f"RAGL{index:03d}",
                    stage="rag_literature",
                    summary=item.excerpt,
                )
            )
        return traces

    @staticmethod
    def _notes_to_traces(
        *,
        notes: list[str],
        round_id: int,
        stage: str,
        prefix: str,
    ) -> list[PlannerReasoningTraceItem]:
        traces: list[PlannerReasoningTraceItem] = []
        for index, note in enumerate(notes[:3], start=1):
            traces.append(
                PlannerReasoningTraceItem(
                    trace_id=f"{prefix}{round_id:02d}{index:02d}",
                    stage=stage,
                    summary=note,
                )
            )
        return traces

    @staticmethod
    def _merge_questioner_uncertainties(
        *,
        uncertainties,
        planner_input: ReasoningPlannerInput,
        proposed: list,
    ):
        existing_questions = {record.question for record in uncertainties.records}
        existing_ids = {record.uncertainty_id for record in uncertainties.records}
        next_index = len(uncertainties.records) + 1
        for item in proposed:
            if item.question in existing_questions:
                continue
            uncertainty_id = item.uncertainty_id or f"U_LLM_R{planner_input.next_round_id:02d}_{next_index:02d}"
            while uncertainty_id in existing_ids:
                next_index += 1
                uncertainty_id = f"U_LLM_R{planner_input.next_round_id:02d}_{next_index:02d}"
            uncertainties.records.append(
                UncertaintyRecord(
                    uncertainty_id=uncertainty_id,
                    question=item.question,
                    description=item.description,
                    related_hypotheses=[entry.hypothesis_id for entry in planner_input.active_hypotheses[:2]],
                    status="active",
                    priority=item.priority if item.priority in {"low", "medium", "high"} else "medium",
                    created_at_round=planner_input.next_round_id,
                    created_by="scientific_questioner_llm",
                    notes="generated_from_scientific_questioner_llm",
                )
            )
            existing_ids.add(uncertainty_id)
            existing_questions.add(item.question)
            next_index += 1
        return uncertainties

    def _log_hypothesis_generation(
        self,
        *,
        round_id: int,
        next_round_id: int,
        generation_result,
        mode: str,
    ) -> None:
        decision_log = self.repository.load_decision_log()
        node_index = generation_result.tree.node_index()
        generated_node_ids = list(generation_result.generated_node_ids)
        decision_log.decisions.append(
            DecisionEntry(
                decision_id=self._next_decision_id(decision_log),
                timestamp=datetime.now(),
                round_id=round_id,
                phase="hypothesis_generation",
                step="programmatic_generation",
                decision_type="hypothesis_generated",
                made_by="system",
                summary=f"已为 round {next_round_id} 程序化生成/扩展假设树",
                details={
                    "mode": mode,
                    "generated_node_ids": generated_node_ids,
                    "generated_hypotheses": [
                        {
                            "hypothesis_id": hypothesis_id,
                            "statement": node_index[hypothesis_id].statement,
                            "generation_rationale": (
                                node_index[hypothesis_id].generation_rationale.model_dump(mode="json", exclude_none=True)
                                if node_index[hypothesis_id].generation_rationale
                                else None
                            ),
                        }
                        for hypothesis_id in generated_node_ids
                    ],
                    "hypothesis_tree_path": self.repository.relativize(self.repository.paths.hypothesis_tree),
                },
            )
        )
        self.repository.save_decision_log(decision_log)

    def _latest_round_review_context(self, decision_log: DecisionLog, round_id: int) -> dict[str, Any]:
        for entry in reversed(decision_log.decisions):
            if entry.round_id == round_id and entry.decision_type == "round_review_requested":
                details = entry.details
                traces = details.get("reasoning_traces", [])
                assessments = details.get("hypothesis_assessments", [])
                context_bits: list[str] = []
                if traces:
                    context_bits.append(f"linked_traces={','.join(item.get('trace_id', '') for item in traces[:3] if item.get('trace_id'))}")
                if assessments:
                    top = assessments[0]
                    context_bits.append(
                        f"assessment:{top.get('hypothesis_id')}->{top.get('status')}"
                    )
                return {
                    "experiment_id": details.get("experiment_id"),
                    "reasoning_trace_ids": [item.get("trace_id") for item in traces if item.get("trace_id")],
                    "context_summary": "; ".join(context_bits) or None,
                }
        return {}

    def _recent_reasoning_traces_for_experiment(self, experiment_id: str) -> list[dict[str, Any]]:
        experiment_memory = self.repository.load_experiment_memory()
        entry = experiment_memory.entry_index().get(experiment_id)
        if entry is None:
            return []
        return [
            trace.model_dump(mode="json", exclude_none=True)
            for trace in entry.reasoning_traces[-5:]
        ]

    def _relevant_protocol_refinements(
        self,
        candidate_id: str,
    ) -> list[ProtocolRefinementSuggestion] | None:
        if not self.repository.paths.planner_output.exists():
            return None
        planner_output = self.repository.load_planner_output()
        refinements = [
            item
            for item in planner_output.protocol_refinements
            if item.target_candidate_id in {None, candidate_id}
        ]
        return refinements or None

    def _build_protocol_refinements(
        self,
        *,
        task: ScientificTask,
        candidate: CandidateExperiment,
    ) -> list[ProtocolRefinementSuggestion] | None:
        refinements = list(self._relevant_protocol_refinements(candidate.experiment_id) or [])
        if self.planner_mode != "llm":
            return refinements or None
        planner_refinement = self.experiment_planner.refine(
            task=task,
            candidate=candidate,
            existing_refinements=refinements,
        )
        refinements.append(planner_refinement)
        return refinements


def _renumber_steps(steps: list[ExperimentStep]) -> list[ExperimentStep]:
    normalized: list[ExperimentStep] = []
    for index, step in enumerate(steps, start=1):
        normalized.append(
            ExperimentStep(
                step=index,
                action=step.action,
                parameters=step.parameters,
            )
        )
    return normalized


def _build_disagreement_steps(candidate: CandidateExperiment) -> list[ExperimentStep]:
    steps: list[ExperimentStep] = []
    for uncertainty_id in candidate.related_uncertainties:
        disagreement = candidate.disagreement_context.get(uncertainty_id, {})
        if not disagreement:
            continue
        compared_hypotheses = list(disagreement.keys())
        source_triggers = sorted(
            {
                item.rationale_trigger
                for item in disagreement.values()
                if hasattr(item, "rationale_trigger") and item.rationale_trigger
            }
        )
        steps.append(
            ExperimentStep(
                step=1,
                action="resolve_disagreement",
                parameters={
                    "uncertainty_id": uncertainty_id,
                    "question": candidate.scientific_question,
                    "compared_hypotheses": compared_hypotheses,
                    "source_triggers": source_triggers,
                },
            )
        )
    return steps


def _disagreement_notes(candidate: CandidateExperiment) -> list[str]:
    notes: list[str] = []
    for uncertainty_id in candidate.related_uncertainties:
        disagreement = candidate.disagreement_context.get(uncertainty_id, {})
        if not disagreement:
            continue
        notes.append(f"targets_uncertainty:{uncertainty_id}")
        notes.append(f"compared_hypotheses:{uncertainty_id}:{','.join(disagreement.keys())}")
        trigger_set = sorted(
            {
                item.rationale_trigger
                for item in disagreement.values()
                if hasattr(item, "rationale_trigger") and item.rationale_trigger
            }
        )
        if trigger_set:
            notes.append(f"disagreement_triggers:{uncertainty_id}:{','.join(trigger_set)}")
    return notes
