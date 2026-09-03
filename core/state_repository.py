from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from core.unified_schema import (
    CandidateExperimentSet,
    DataDictionary,
    DecisionLog,
    ExperimentMemoryState,
    FailureHistoryState,
    HypothesisNode,
    HypothesisTreeState,
    LatestTreeUpdate,
    MetricsTimelineState,
    ReasoningPlannerInput,
    ProcessPhase,
    ProcessState,
    ProcessStep,
    RoundHistoryState,
    ScientificTask,
    TreeSummary,
    UncertaintyPriorityQueue,
    UncertaintyRecord,
    UncertaintyState,
    UserRequests,
    UserSettings,
)


SchemaModelT = TypeVar("SchemaModelT")


@dataclass(frozen=True)
class StatePaths:
    root: Path
    task: Path
    data_dictionary: Path
    hypothesis_tree: Path
    uncertainties: Path
    uncertainty_priority: Path
    experiment_memory: Path
    round_history: Path
    metrics_timeline: Path
    failure_history: Path
    process_state: Path
    decision_log: Path
    candidate_experiments: Path
    planner_input: Path
    planner_output: Path


class UnifiedStateRepository:
    """Read and write persistent workflow states under the project-relative state directory."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parent.parent
        self.state_dir = self.project_root / "state"
        self.paths = StatePaths(
            root=self.state_dir,
            task=self.state_dir / "task.json",
            data_dictionary=self.state_dir / "data_dictionary.json",
            hypothesis_tree=self.state_dir / "hypothesis_tree.json",
            uncertainties=self.state_dir / "uncertainties.json",
            uncertainty_priority=self.state_dir / "uncertainty_priority.json",
            experiment_memory=self.state_dir / "experiment_memory.json",
            round_history=self.state_dir / "round_history.json",
            metrics_timeline=self.state_dir / "metrics_timeline.json",
            failure_history=self.state_dir / "failure_history.json",
            process_state=self.state_dir / "process.json",
            decision_log=self.state_dir / "decision_log.json",
            candidate_experiments=self.state_dir / "candidate_experiments.json",
            planner_input=self.state_dir / "planner_input.json",
            planner_output=self.state_dir / "planner_output.json",
        )

    def initialize_state_skeleton(
        self,
        task: ScientificTask,
        *,
        initial_hypotheses: list[HypothesisNode] | None = None,
        initial_uncertainties: list[UncertaintyRecord] | None = None,
        data_dictionary: DataDictionary | None = None,
        planner_input: ReasoningPlannerInput | None = None,
        overwrite: bool = False,
    ) -> dict[str, object]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        generated_node_ids: tuple[str, ...] = ()
        if initial_hypotheses is None and data_dictionary is not None:
            from core.hypothesis_generation import HypothesisGenerationService

            generated = HypothesisGenerationService().build_tree(
                task=task,
                data_dictionary=data_dictionary,
                uncertainties=initial_uncertainties or [],
                planner_input=planner_input,
                current_round=0,
            )
            tree = generated.tree
            generated_node_ids = generated.generated_node_ids
            initial_uncertainties = list(generated.updated_uncertainties)
        else:
            tree = HypothesisTreeState(
                tree_id=f"{task.task_id}_tree",
                task_id=task.task_id,
                current_round=0,
                root_question=task.payload.research_question.text,
                nodes=initial_hypotheses or [],
                active_hypotheses=[node.hypothesis_id for node in initial_hypotheses or [] if node.status == "active"],
                pruned_hypotheses=[node.hypothesis_id for node in initial_hypotheses or [] if node.status == "pruned"],
                pending_hypotheses=[
                    node.hypothesis_id for node in initial_hypotheses or [] if node.status in {"draft", "pending"}
                ],
                latest_update=LatestTreeUpdate(
                    round=0,
                    event="initialized",
                    description="knowledge memory skeleton created",
                ),
                tree_summary=_build_tree_summary(initial_hypotheses or []),
            )
        queue = UncertaintyPriorityQueue(
            last_updated=now,
            current_round=0,
            queue=[],
            resolved=[],
            deprecated=[],
        )
        uncertainties = UncertaintyState(
            task_id=task.task_id,
            current_round=0,
            last_updated=now,
            records=initial_uncertainties or [],
            priority_queue=queue,
        )
        experiment_memory = ExperimentMemoryState(
            task_id=task.task_id,
            current_round=0,
            last_updated=now,
            entries=[],
        )
        round_history = RoundHistoryState(
            task_id=task.task_id,
            current_round=0,
            last_updated=now,
            entries=[],
        )
        metrics_timeline = MetricsTimelineState(
            task_id=task.task_id,
            current_round=0,
            last_updated=now,
            entries=[],
        )
        failure_history = FailureHistoryState(
            task_id=task.task_id,
            current_round=0,
            last_updated=now,
            records=[],
        )
        process_state = ProcessState(
            task_id=task.task_id,
            current_round=0,
            current_stage="state_initialized",
            current_phase="task_definition",
            current_step="confirmation",
            progress_percentage=5,
            started_at=now,
            phase_sequence=[
                "task_definition",
                "hypothesis_generation",
                "experiment_planning",
                "experiment_execution",
                "result_analysis",
                "decision_making",
                "next_round",
            ],
            phases={
                "task_definition": ProcessPhase(
                    status="completed",
                    completed_at=now,
                    notes="scientific task saved and confirmed",
                    steps={
                        "confirmation": ProcessStep(name="confirmation", status="completed", requires_user_approval=True)
                    },
                ),
                "hypothesis_generation": ProcessPhase(status="pending"),
                "experiment_planning": ProcessPhase(status="pending"),
                "experiment_execution": ProcessPhase(status="pending"),
                "result_analysis": ProcessPhase(status="pending"),
                "decision_making": ProcessPhase(status="pending"),
                "next_round": ProcessPhase(status="pending"),
            },
            steps={
                "task_definition": ProcessStep(name="task_definition", status="completed"),
                "state_bootstrap": ProcessStep(name="state_bootstrap", status="completed"),
            },
            user_settings=UserSettings(
                auto_continue=False,
                stop_at_each_step=True,
                approval_required=["experiment_selection", "protocol_validation", "round_completion"],
            ),
            user_requests=UserRequests(),
        )
        decision_log = DecisionLog(task_id=task.task_id)
        if generated_node_ids:
            process_state.phases["hypothesis_generation"] = ProcessPhase(
                status="completed",
                completed_at=now,
                notes="programmatic initial hypothesis tree generated",
                steps={
                    "programmatic_generation": ProcessStep(
                        name="programmatic_generation",
                        status="completed",
                        requires_user_approval=False,
                    )
                },
            )

        if overwrite or not self.paths.task.exists():
            self.save_task(task)
        if data_dictionary is not None and (overwrite or not self.paths.data_dictionary.exists()):
            self.save_data_dictionary(data_dictionary)
        if overwrite or not self.paths.hypothesis_tree.exists():
            self.save_hypothesis_tree(tree)
        if overwrite or not self.paths.uncertainties.exists():
            self.save_uncertainties(uncertainties)
        if overwrite or not self.paths.experiment_memory.exists():
            self.save_experiment_memory(experiment_memory)
        if overwrite or not self.paths.round_history.exists():
            self.save_round_history(round_history)
        if overwrite or not self.paths.metrics_timeline.exists():
            self.save_metrics_timeline(metrics_timeline)
        if overwrite or not self.paths.failure_history.exists():
            self.save_failure_history(failure_history)
        if overwrite or not self.paths.process_state.exists():
            self.save_process_state(process_state)
        if overwrite or not self.paths.decision_log.exists():
            self.save_decision_log(decision_log)

        return {
            "task": task,
            "hypothesis_tree": tree,
            "uncertainties": uncertainties,
            "experiment_memory": experiment_memory,
            "process_state": process_state,
            "decision_log": decision_log,
        }

    def load_task(self) -> ScientificTask:
        return self._load_model(self.paths.task, ScientificTask)

    def save_task(self, task: ScientificTask) -> None:
        self._save_model(self.paths.task, task)

    def load_data_dictionary(self) -> DataDictionary:
        return self._load_model(self.paths.data_dictionary, DataDictionary)

    def save_data_dictionary(self, data_dictionary: DataDictionary) -> None:
        self._save_model(self.paths.data_dictionary, data_dictionary)

    def load_hypothesis_tree(self) -> HypothesisTreeState:
        return self._load_model(self.paths.hypothesis_tree, HypothesisTreeState)

    def save_hypothesis_tree(self, state: HypothesisTreeState) -> None:
        self._save_model(self.paths.hypothesis_tree, state)

    def load_uncertainties(self) -> UncertaintyState:
        return self._load_model(self.paths.uncertainties, UncertaintyState)

    def save_uncertainties(self, state: UncertaintyState) -> None:
        self._save_model(self.paths.uncertainties, state)
        if state.priority_queue is not None:
            self._save_model(self.paths.uncertainty_priority, state.priority_queue)

    def load_experiment_memory(self) -> ExperimentMemoryState:
        return self._load_model(self.paths.experiment_memory, ExperimentMemoryState)

    def save_experiment_memory(self, state: ExperimentMemoryState) -> None:
        self._save_model(self.paths.experiment_memory, state)

    def load_round_history(self) -> RoundHistoryState:
        return self._load_model(self.paths.round_history, RoundHistoryState)

    def save_round_history(self, state: RoundHistoryState) -> None:
        self._save_model(self.paths.round_history, state)

    def load_metrics_timeline(self) -> MetricsTimelineState:
        return self._load_model(self.paths.metrics_timeline, MetricsTimelineState)

    def save_metrics_timeline(self, state: MetricsTimelineState) -> None:
        self._save_model(self.paths.metrics_timeline, state)

    def load_failure_history(self) -> FailureHistoryState:
        return self._load_model(self.paths.failure_history, FailureHistoryState)

    def save_failure_history(self, state: FailureHistoryState) -> None:
        self._save_model(self.paths.failure_history, state)

    def load_process_state(self) -> ProcessState:
        return self._load_model(self.paths.process_state, ProcessState)

    def save_process_state(self, state: ProcessState) -> None:
        self._save_model(self.paths.process_state, state)

    def load_decision_log(self) -> DecisionLog:
        return self._load_model(self.paths.decision_log, DecisionLog)

    def save_decision_log(self, state: DecisionLog) -> None:
        self._save_model(self.paths.decision_log, state)

    def load_candidate_experiments(self) -> CandidateExperimentSet:
        return self._load_model(self.paths.candidate_experiments, CandidateExperimentSet)

    def save_candidate_experiments(self, state: CandidateExperimentSet) -> None:
        self._save_model(self.paths.candidate_experiments, state)

    def load_planner_input(self) -> ReasoningPlannerInput:
        return self._load_model(self.paths.planner_input, ReasoningPlannerInput)

    def save_planner_input(self, state: ReasoningPlannerInput) -> None:
        self._save_model(self.paths.planner_input, state)

    def load_planner_output(self):
        from core.unified_schema import ReasoningPlannerOutput

        return self._load_model(self.paths.planner_output, ReasoningPlannerOutput)

    def save_planner_output(self, state) -> None:
        self._save_model(self.paths.planner_output, state)

    def relativize(self, path: str | Path | None) -> str | None:
        if path is None:
            return None
        candidate = Path(path)
        try:
            return candidate.resolve().relative_to(self.project_root.resolve()).as_posix()
        except ValueError:
            return candidate.as_posix()

    def _save_model(self, file_path: Path, model: object) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = getattr(model, "model_dump")(mode="json", exclude_none=True)
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_model(self, file_path: Path, model_cls: type[SchemaModelT]) -> SchemaModelT:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        return model_cls.model_validate(payload)


def _build_tree_summary(nodes: list[HypothesisNode]) -> TreeSummary:
    return TreeSummary(
        total_nodes=len(nodes),
        active_count=sum(1 for node in nodes if node.status == "active"),
        pruned_count=sum(1 for node in nodes if node.status == "pruned"),
        pending_count=sum(1 for node in nodes if node.status in {"draft", "pending"}),
    )
