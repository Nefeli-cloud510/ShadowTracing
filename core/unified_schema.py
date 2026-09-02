from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MetricName = Literal["RMSE", "MAE", "Pearson_r", "Skill", "R2"]
HypothesisStatus = Literal[
    "draft",
    "pending",
    "active",
    "observing",
    "converged",
    "supported",
    "partially_supported",
    "weakened",
    "pruned",
]
EvidenceType = Literal["literature", "observational_data", "experimental_result", "physical_prior", "expert_judgment"]
DecisionType = Literal[
    "task_approved",
    "task_revised",
    "hypothesis_generated",
    "experiment_selection_requested",
    "experiment_approved",
    "experiment_rejected",
    "experiment_modified",
    "protocol_generated",
    "stop_requested",
    "pause_requested",
    "round_review_requested",
    "scientific_interpreter_applied",
    "planner_input_prepared",
    "planner_output_generated",
    "planner_output_applied",
    "round_completed",
    "continue_next_round",
    "round_adjusted",
    "terminate_workflow",
]
UncertaintyStatus = Literal["identified", "active", "experimenting", "resolved", "deprecated"]
PriorityLevel = Literal["low", "medium", "high"]
ExpectedEffect = Literal["positive", "negative", "near_zero", "nonlinear", "unknown"]
ExecutionStatus = Literal["queued", "running", "completed", "failed", "aborted"]
StepStatus = Literal["pending", "in_progress", "completed", "failed", "skipped"]


class ShadowBaseModel(BaseModel):
    """Base configuration shared by all unified schemas."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    def to_pretty_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class VariableBinding(ShadowBaseModel):
    x: str = Field(description="Primary explanatory variable")
    y: str = Field(description="Target variable")
    m_candidates: list[str] = Field(default_factory=list, description="Candidate mediator variables")


class ResearchQuestion(ShadowBaseModel):
    text: str = Field(min_length=1, description="Natural-language scientific question")
    target: str = Field(min_length=1, description="Primary optimization target")
    question_type: str = Field(min_length=1, description="Question type or task category")
    variables: VariableBinding | None = Field(default=None, description="Structured variable bindings")
    keywords: list[str] = Field(default_factory=list)
    clarified: bool = False


class EvaluationSpec(ShadowBaseModel):
    primary_metric: MetricName = Field(default="RMSE")
    secondary_metrics: list[MetricName] = Field(default_factory=list)
    visual_analysis: list[str] = Field(default_factory=list)

    @field_validator("secondary_metrics")
    @classmethod
    def unique_secondary_metrics(cls, value: list[MetricName]) -> list[MetricName]:
        return list(dict.fromkeys(value))


class ScientificConstraints(ShadowBaseModel):
    no_future_information: bool = True
    validation_feedback_allowed: bool = True
    final_test_blind: bool = True
    max_hypotheses_per_level: int | None = Field(default=None, ge=1)
    min_active_hypotheses: int | None = Field(default=None, ge=1)
    max_rounds: int | None = Field(default=None, ge=1)
    max_experiments_per_round: int | None = Field(default=None, ge=1)
    resource_budget: "ResourceBudget | None" = None
    notes: list[str] = Field(default_factory=list)


class ScientificTaskPayload(ShadowBaseModel):
    research_question: ResearchQuestion
    evaluation: EvaluationSpec
    constraints: ScientificConstraints
    data_sources: dict[str, Any] = Field(default_factory=dict)


class ScientificTask(ShadowBaseModel):
    schema_version: str = "1.0"
    message_type: Literal["scientific_task"] = "scientific_task"
    task_id: str = Field(min_length=1)
    producer: Literal["human_pi"] = "human_pi"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    payload: ScientificTaskPayload


class FieldDescriptor(ShadowBaseModel):
    field_name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    physical_meaning: str = Field(min_length=1)
    unit: str | None = None
    format: str | None = None
    range: list[float | int] | None = None
    missing_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    is_target: bool = False
    user_notes: str | None = None


class DataDictionary(ShadowBaseModel):
    dictionary_id: str = Field(min_length=1)
    generated_at: datetime
    version: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    total_samples: int = Field(ge=0)
    time_column: str = Field(min_length=1)
    time_format: str = Field(min_length=1)
    time_range: dict[str, str] | None = None
    fields: list[FieldDescriptor] = Field(default_factory=list)
    target_candidates: list[str] = Field(default_factory=list)
    feature_candidates: list[str] = Field(default_factory=list)
    user_supplementary: dict[str, str] = Field(default_factory=dict)

    @field_validator("fields")
    @classmethod
    def unique_field_names(cls, value: list[FieldDescriptor]) -> list[FieldDescriptor]:
        names = [item.field_name for item in value]
        if len(names) != len(set(names)):
            raise ValueError("DataDictionary.fields contains duplicate field names")
        return value

    def get_available_fields(self) -> list[str]:
        return [item.field_name for item in self.fields]


class EvidenceItem(ShadowBaseModel):
    id: str = Field(min_length=1)
    type: EvidenceType
    description: str = Field(min_length=1)
    source: str = Field(min_length=1)
    added_at_round: int = Field(ge=0)
    support_weight: float | None = Field(default=None, ge=0.0, le=1.0)


class CritiqueRecord(ShadowBaseModel):
    id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    from_role: str = Field(min_length=1)
    added_at_round: int = Field(ge=0)
    resolved: bool = False


class PredictionRecord(ShadowBaseModel):
    experiment_id: str = Field(min_length=1)
    metric: MetricName
    expected_direction: ExpectedEffect | str
    expected_range: list[float] | None = None
    actual_value: float | None = None
    matched: bool | Literal["partial"] | None = None

    @field_validator("expected_range")
    @classmethod
    def validate_expected_range(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and len(value) != 2:
            raise ValueError("expected_range must contain exactly two values")
        return value


class SupportHistoryEntry(ShadowBaseModel):
    round: int = Field(ge=0)
    score: float = Field(ge=0.0, le=1.0)
    event: str = Field(min_length=1)


class HypothesisSourceSignal(ShadowBaseModel):
    signal_type: str = Field(min_length=1)
    source_id: str | None = None
    source_round: int | None = Field(default=None, ge=0)
    excerpt: str = Field(min_length=1)
    weight: float = Field(default=0.5, ge=0.0, le=1.0)


class HypothesisGenerationRationale(ShadowBaseModel):
    trigger: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    linked_uncertainties: list[str] = Field(default_factory=list)
    derived_features: list[str] = Field(default_factory=list)
    source_signals: list[HypothesisSourceSignal] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class HypothesisNode(ShadowBaseModel):
    hypothesis_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    level: int = Field(ge=1)
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    status: HypothesisStatus = "draft"
    support_score: float = Field(ge=0.0, le=1.0)
    support_history: list[SupportHistoryEntry] = Field(default_factory=list)
    activation_condition: str = Field(min_length=1)
    activated_at_round: int | None = Field(default=None, ge=0)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    evidence_against: list[EvidenceItem] = Field(default_factory=list)
    critiques: list[CritiqueRecord] = Field(default_factory=list)
    predictions: list[PredictionRecord] = Field(default_factory=list)
    falsification_conditions: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    pruned_at_round: int | None = Field(default=None, ge=0)
    prune_reason: str | None = None
    created_at_round: int = Field(default=0, ge=0)
    updated_at_round: int = Field(default=0, ge=0)
    generation_rationale: HypothesisGenerationRationale | None = None


class TreeSummary(ShadowBaseModel):
    total_nodes: int = Field(ge=0)
    active_count: int = Field(ge=0)
    pruned_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)


class LatestTreeUpdate(ShadowBaseModel):
    round: int = Field(ge=0)
    event: str = Field(min_length=1)
    description: str = Field(min_length=1)


class HypothesisTreeState(ShadowBaseModel):
    tree_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    current_round: int = Field(ge=0, default=0)
    root_question: str = Field(min_length=1)
    nodes: list[HypothesisNode] = Field(default_factory=list)
    active_hypotheses: list[str] = Field(default_factory=list)
    pruned_hypotheses: list[str] = Field(default_factory=list)
    pending_hypotheses: list[str] = Field(default_factory=list)
    latest_update: LatestTreeUpdate | None = None
    tree_summary: TreeSummary | None = None

    @field_validator("nodes")
    @classmethod
    def unique_hypothesis_ids(cls, value: list[HypothesisNode]) -> list[HypothesisNode]:
        ids = [item.hypothesis_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("HypothesisTreeState.nodes contains duplicate hypothesis_id")
        return value

    @model_validator(mode="after")
    def validate_indexes(self) -> "HypothesisTreeState":
        node_ids = {node.hypothesis_id for node in self.nodes}
        for group_name, items in (
            ("active_hypotheses", self.active_hypotheses),
            ("pruned_hypotheses", self.pruned_hypotheses),
            ("pending_hypotheses", self.pending_hypotheses),
        ):
            missing = set(items) - node_ids
            if missing:
                raise ValueError(f"{group_name} contains unknown hypotheses: {sorted(missing)}")
        return self

    def node_index(self) -> dict[str, HypothesisNode]:
        return {node.hypothesis_id: node for node in self.nodes}


class UncertaintyDisagreement(ShadowBaseModel):
    hypothesis_id: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    status: HypothesisStatus | str
    support_score: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale_trigger: str | None = None
    source_summary: str | None = None


class PriorityFactors(ShadowBaseModel):
    hypothesis_count: int = Field(ge=0)
    support_gap: float = Field(ge=0.0, le=1.0)
    expected_information_gain: float = Field(ge=0.0, le=1.0)
    estimated_cost: float = Field(ge=0.0, le=1.0)
    human_priority_override: float | None = Field(default=None, ge=0.0, le=1.0)


class UncertaintyHistoryEntry(ShadowBaseModel):
    round: int = Field(ge=0)
    event: str = Field(min_length=1)
    source: str = Field(min_length=1)
    description: str = Field(min_length=1)


class UncertaintyRecord(ShadowBaseModel):
    uncertainty_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    description: str = Field(min_length=1)
    related_hypotheses: list[str] = Field(default_factory=list)
    disagreement: dict[str, UncertaintyDisagreement | dict[str, Any]] = Field(default_factory=dict)
    status: UncertaintyStatus = "identified"
    priority: PriorityLevel = "medium"
    priority_factors: PriorityFactors | None = None
    created_at_round: int = Field(ge=0)
    created_by: str = Field(min_length=1)
    resolved_at_round: int | None = Field(default=None, ge=0)
    resolved_by: str | None = None
    resolution: str | None = None
    resolution_status: Literal["resolved", "partially_resolved", "unresolved"] | None = None
    resolving_experiment: str | None = None
    history: list[UncertaintyHistoryEntry] = Field(default_factory=list)
    alternative_resolutions: list[str] = Field(default_factory=list)
    notes: str | None = None


class PrioritizedUncertainty(ShadowBaseModel):
    uncertainty_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    priority_score: float = Field(ge=0.0, le=1.0)
    status: UncertaintyStatus | str
    estimated_resolution_round: int | None = Field(default=None, ge=0)


class UncertaintyPriorityQueue(ShadowBaseModel):
    last_updated: datetime
    current_round: int = Field(ge=0)
    queue: list[PrioritizedUncertainty] = Field(default_factory=list)
    resolved: list[str] = Field(default_factory=list)
    deprecated: list[str] = Field(default_factory=list)

    def top_uncertainties(self, limit: int = 3) -> list[PrioritizedUncertainty]:
        return sorted(self.queue, key=lambda item: item.priority_score, reverse=True)[:limit]


class ExperimentDesign(ShadowBaseModel):
    target: str = Field(min_length=1)
    control: list[str] = Field(default_factory=list)
    treatment: list[str] = Field(default_factory=list)
    lags: dict[str, list[int]] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class HypothesisPrediction(ShadowBaseModel):
    expected_effect: ExpectedEffect | str
    expected_range: list[float] | None = None

    @field_validator("expected_range")
    @classmethod
    def validate_range(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and len(value) != 2:
            raise ValueError("expected_range must contain exactly two values")
        return value


class EstimatedValue(ShadowBaseModel):
    value: float = Field(ge=0.0, le=1.0)
    rationale: str | None = None


class CandidateExperiment(ShadowBaseModel):
    experiment_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    scientific_question: str | None = None
    tested_hypotheses: list[str] = Field(default_factory=list)
    related_uncertainties: list[str] = Field(default_factory=list)
    disagreement_context: dict[str, dict[str, UncertaintyDisagreement | dict[str, Any]]] = Field(default_factory=dict)
    hypothesis_source_context: dict[str, HypothesisGenerationRationale | dict[str, Any]] = Field(default_factory=dict)
    design: ExperimentDesign
    hypothesis_predictions: dict[str, HypothesisPrediction] = Field(default_factory=dict)
    distinguishing_insight: str | None = None
    estimated_information_gain: EstimatedValue | None = None
    estimated_performance_gain: EstimatedValue | None = None
    estimated_risk: EstimatedValue | None = None
    estimated_cost: EstimatedValue | None = None
    utility_score: float | None = Field(default=None, ge=0.0, le=1.0)
    requires_human_review: bool = False
    novelty: str | None = None


class RejectedCandidate(ShadowBaseModel):
    experiment_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    similar_to: str | None = None


class CandidateExperimentSet(ShadowBaseModel):
    round: int = Field(ge=0)
    generated_at: datetime
    candidates: list[CandidateExperiment] = Field(default_factory=list)
    rejected_candidates: list[RejectedCandidate] = Field(default_factory=list)
    minimum_required: int = Field(default=3, ge=1)
    current_count: int | None = Field(default=None, ge=0)
    note: str | None = None

    @field_validator("candidates")
    @classmethod
    def unique_experiment_ids(cls, value: list[CandidateExperiment]) -> list[CandidateExperiment]:
        ids = [item.experiment_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("CandidateExperimentSet contains duplicate experiment_id")
        return value

    @model_validator(mode="after")
    def populate_current_count(self) -> "CandidateExperimentSet":
        if self.current_count is None:
            self.current_count = len(self.candidates)
        return self

    def top_candidate(self) -> CandidateExperiment | None:
        scored = [item for item in self.candidates if item.utility_score is not None]
        if not scored:
            return None
        return max(scored, key=lambda item: item.utility_score or 0.0)


class ResourceBudget(ShadowBaseModel):
    token_budget: int | None = Field(default=None, ge=0)
    max_time_seconds_per_round: int | None = Field(default=None, ge=0)
    max_candidates: int | None = Field(default=None, ge=1)


class ModelSpec(ShadowBaseModel):
    name: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExperimentStep(ShadowBaseModel):
    step: int = Field(ge=1)
    action: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProtocolConstraints(ShadowBaseModel):
    no_future_information: bool = True
    target_immutable: bool = True


class ExperimentProtocol(ShadowBaseModel):
    experiment_id: str = Field(min_length=1)
    round_id: int = Field(ge=0)
    task_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    scientific_objective: str | None = None
    forecast_horizon_days: int | None = Field(default=None, ge=1)
    features: ExperimentDesign
    model: ModelSpec = Field(default_factory=lambda: ModelSpec(name="ElasticNet"))
    tested_hypotheses: list[str] = Field(default_factory=list)
    target_uncertainties: list[str] = Field(default_factory=list)
    disagreement_context: dict[str, dict[str, UncertaintyDisagreement | dict[str, Any]]] = Field(default_factory=dict)
    hypothesis_source_context: dict[str, HypothesisGenerationRationale | dict[str, Any]] = Field(default_factory=dict)
    hypothesis_predictions: dict[str, HypothesisPrediction] = Field(default_factory=dict)
    evaluation_metrics: list[MetricName] = Field(default_factory=lambda: ["RMSE", "MAE", "Pearson_r", "Skill"])
    budget: ResourceBudget | None = None
    steps: list[ExperimentStep] = Field(default_factory=list)
    constraints: ProtocolConstraints = Field(default_factory=ProtocolConstraints)
    source_candidate_id: str | None = None
    requires_human_review: bool = False
    notes: list[str] = Field(default_factory=list)


class RunMetrics(ShadowBaseModel):
    rmse: float | None = None
    mae: float | None = None
    pearson_r: float | None = None
    skill: float | None = None
    r2: float | None = None


class ExperimentRun(ShadowBaseModel):
    run_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    prediction_artifact: str | None = None
    metrics: RunMetrics = Field(default_factory=RunMetrics)


class MetricDelta(ShadowBaseModel):
    rmse: float | None = None
    mae: float | None = None
    pearson_r: float | None = None
    skill: float | None = None
    r2: float | None = None


class VisualizationArtifact(ShadowBaseModel):
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)


class ExecutionSummary(ShadowBaseModel):
    duration_seconds: float | None = Field(default=None, ge=0.0)
    compute_seconds: float | None = Field(default=None, ge=0.0)
    status: ExecutionStatus
    message: str | None = None


class ExperimentResult(ShadowBaseModel):
    experiment_id: str = Field(min_length=1)
    round_id: int = Field(ge=0)
    status: ExecutionStatus
    runs: list[ExperimentRun] = Field(default_factory=list)
    comparison: MetricDelta = Field(default_factory=MetricDelta)
    visualizations: list[VisualizationArtifact] = Field(default_factory=list)
    execution: ExecutionSummary


class PerformanceMetrics(ShadowBaseModel):
    experiment_id: str = Field(min_length=1)
    round_id: int = Field(ge=0)
    baseline_rmse: float | None = None
    baseline_mae: float | None = None
    baseline_pearson_r: float | None = None
    baseline_skill: float | None = None
    treatment_rmse: float | None = None
    treatment_mae: float | None = None
    treatment_pearson_r: float | None = None
    treatment_skill: float | None = None
    pg_actual_signed: float | None = None
    pg_actual_clipped: float | None = Field(default=None, ge=0.0, le=1.0)
    delta: MetricDelta = Field(default_factory=MetricDelta)


class BootstrapReport(ShadowBaseModel):
    pearson_r_ci: list[float] | None = None
    rmse_ci: list[float] | None = None
    skill_ci: list[float] | None = None
    stable: bool
    n_iterations: int | None = Field(default=None, ge=0)


class TimeSliceFold(ShadowBaseModel):
    fold: int = Field(ge=1)
    pearson_r: float | None = None
    rmse: float | None = None
    skill: float | None = None


class TimeSliceReport(ShadowBaseModel):
    splits: list[TimeSliceFold] = Field(default_factory=list)
    std_pearson_r: float | None = None
    stable: bool


class RobustnessOverall(ShadowBaseModel):
    stable: bool
    concern: str | None = None


class RobustnessReport(ShadowBaseModel):
    bootstrap: BootstrapReport | None = None
    time_slice: TimeSliceReport | None = None
    overall: RobustnessOverall
    recommendation: str | None = None


class HypothesisAssessment(ShadowBaseModel):
    hypothesis_id: str = Field(min_length=1)
    support_before: float = Field(ge=0.0, le=1.0)
    support_after: float = Field(ge=0.0, le=1.0)
    status: HypothesisStatus | Literal["supported", "partially_supported", "weakened"]
    direction_matched: bool | Literal["partial"]
    magnitude_matched: bool | Literal["partial"]
    reason: str = Field(min_length=1)


class EvidenceClaim(ShadowBaseModel):
    claim: str = Field(min_length=1)
    strength: PriorityLevel | str
    source: str | None = None


class EvidenceSummary(ShadowBaseModel):
    new_evidence_for: list[EvidenceClaim] = Field(default_factory=list)
    new_evidence_against: list[EvidenceClaim] = Field(default_factory=list)
    remaining_uncertainties: list[dict[str, Any]] = Field(default_factory=list)


class DisagreementUpdate(ShadowBaseModel):
    uncertainty_id: str = Field(min_length=1)
    compared_hypotheses: list[str] = Field(default_factory=list)
    support_span_before: float = Field(ge=0.0, le=1.0)
    support_span_after: float = Field(ge=0.0, le=1.0)
    narrowed: bool = False
    resolution_status: Literal["resolved", "partially_resolved", "unresolved"] = "unresolved"
    leading_hypothesis_id: str | None = None
    unresolved_hypotheses: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class ScientificEvaluation(ShadowBaseModel):
    experiment_id: str = Field(min_length=1)
    round_id: int = Field(ge=0)
    hypothesis_assessments: list[HypothesisAssessment] = Field(default_factory=list)
    disagreement_updates: list[DisagreementUpdate] = Field(default_factory=list)
    evidence_summary: EvidenceSummary = Field(default_factory=EvidenceSummary)


class EvaluationResult(ShadowBaseModel):
    metrics: PerformanceMetrics
    robustness: RobustnessReport
    scientific: ScientificEvaluation
    visualizations: list[VisualizationArtifact] = Field(default_factory=list)

    def to_interpreter_payload(self) -> dict[str, Any]:
        return {
            "performance_metrics": self.metrics.model_dump(exclude_none=True),
            "robustness": self.robustness.model_dump(exclude_none=True),
            "hypothesis_assessments": [
                item.model_dump(exclude_none=True) for item in self.scientific.hypothesis_assessments
            ],
            "visualizations": [item.model_dump(exclude_none=True) for item in self.visualizations],
            "remaining_uncertainties": self.scientific.evidence_summary.remaining_uncertainties,
        }


class PlannerUncertaintyItem(ShadowBaseModel):
    uncertainty_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    priority: PriorityLevel | str
    priority_score: float | None = Field(default=None, ge=0.0, le=1.0)
    status: UncertaintyStatus | str | None = None
    resolution_status: Literal["resolved", "partially_resolved", "unresolved"] | None = None
    related_hypotheses: list[str] = Field(default_factory=list)


class HypothesisSnapshot(ShadowBaseModel):
    hypothesis_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    status: HypothesisStatus | str
    support_score: float = Field(ge=0.0, le=1.0)


class DataDictionarySummary(ShadowBaseModel):
    dictionary_id: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    time_column: str = Field(min_length=1)
    target_candidates: list[str] = Field(default_factory=list)
    feature_candidates: list[str] = Field(default_factory=list)


class PlannerEvaluationSummary(ShadowBaseModel):
    experiment_id: str | None = None
    round_id: int = Field(ge=0)
    baseline_rmse: float | None = None
    treatment_rmse: float | None = None
    baseline_pearson_r: float | None = None
    treatment_pearson_r: float | None = None
    delta_pearson_r: float | None = None
    delta_rmse: float | None = None
    pg_actual_signed: float | None = None
    pg_actual_clipped: float | None = Field(default=None, ge=0.0, le=1.0)
    key_findings: list[str] = Field(default_factory=list)
    robustness_recommendation: str | None = None
    stable: bool | None = None


class PlannerReasoningTraceItem(ShadowBaseModel):
    trace_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    related_hypotheses: list[str] = Field(default_factory=list)
    related_uncertainties: list[str] = Field(default_factory=list)
    support_delta: float | None = Field(default=None, ge=-1.0, le=1.0)
    priority_delta: float | None = Field(default=None, ge=-1.0, le=1.0)


class PlannerHumanFeedbackItem(ShadowBaseModel):
    feedback_id: str = Field(min_length=1)
    feedback_type: str = Field(min_length=1)
    content: str = Field(min_length=1)
    linked_reasoning_trace_ids: list[str] = Field(default_factory=list)
    related_experiment_id: str | None = None
    context_summary: str | None = None


class PlannerDisagreementUpdateItem(ShadowBaseModel):
    uncertainty_id: str = Field(min_length=1)
    resolution_status: Literal["resolved", "partially_resolved", "unresolved"]
    compared_hypotheses: list[str] = Field(default_factory=list)
    narrowed: bool = False
    leading_hypothesis_id: str | None = None
    unresolved_hypotheses: list[str] = Field(default_factory=list)
    support_span_before: float = Field(ge=0.0, le=1.0)
    support_span_after: float = Field(ge=0.0, le=1.0)
    summary: str = Field(min_length=1)


class ReasoningPlannerInput(ShadowBaseModel):
    task_id: str = Field(min_length=1)
    source_round_id: int = Field(ge=0)
    next_round_id: int = Field(ge=0)
    source_experiment_id: str | None = None
    scientific_question: str = Field(min_length=1)
    target: str = Field(min_length=1)
    human_feedback: str | None = None
    evaluation_summary: PlannerEvaluationSummary
    unresolved_uncertainties: list[PlannerUncertaintyItem] = Field(default_factory=list)
    active_hypotheses: list[HypothesisSnapshot] = Field(default_factory=list)
    recent_hypothesis_assessments: list[HypothesisAssessment] = Field(default_factory=list)
    recent_disagreement_updates: list[PlannerDisagreementUpdateItem] = Field(default_factory=list)
    recent_reasoning_traces: list[PlannerReasoningTraceItem] = Field(default_factory=list)
    recent_human_feedback: list[PlannerHumanFeedbackItem] = Field(default_factory=list)
    data_dictionary_summary: DataDictionarySummary
    planning_constraints: dict[str, Any] = Field(default_factory=dict)
    planner_guidance: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)

    def to_central_controller_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source_round_id": self.source_round_id,
            "next_round_id": self.next_round_id,
            "scientific_question": self.scientific_question,
            "target": self.target,
            "human_feedback": self.human_feedback,
            "evaluation_summary": self.evaluation_summary.model_dump(exclude_none=True),
            "recent_hypothesis_assessments": [
                item.model_dump(exclude_none=True) for item in self.recent_hypothesis_assessments
            ],
            "recent_disagreement_updates": [
                item.model_dump(exclude_none=True) for item in self.recent_disagreement_updates
            ],
            "recent_human_feedback": [
                item.model_dump(exclude_none=True) for item in self.recent_human_feedback
            ],
            "planner_guidance": self.planner_guidance,
        }

    def to_experiment_planner_payload(self) -> dict[str, Any]:
        return {
            "source_experiment_id": self.source_experiment_id,
            "human_feedback": self.human_feedback,
            "unresolved_uncertainties": [
                item.model_dump(exclude_none=True) for item in self.unresolved_uncertainties
            ],
            "active_hypotheses": [
                item.model_dump(exclude_none=True) for item in self.active_hypotheses
            ],
            "recent_disagreement_updates": [
                item.model_dump(exclude_none=True) for item in self.recent_disagreement_updates
            ],
            "recent_reasoning_traces": [
                item.model_dump(exclude_none=True) for item in self.recent_reasoning_traces
            ],
            "recent_human_feedback": [
                item.model_dump(exclude_none=True) for item in self.recent_human_feedback
            ],
            "data_dictionary_summary": self.data_dictionary_summary.model_dump(exclude_none=True),
            "planner_guidance": self.planner_guidance,
        }

    def to_scientific_interpreter_payload(self) -> dict[str, Any]:
        return {
            "source_round_id": self.source_round_id,
            "evaluation_summary": self.evaluation_summary.model_dump(exclude_none=True),
            "recent_hypothesis_assessments": [
                item.model_dump(exclude_none=True) for item in self.recent_hypothesis_assessments
            ],
            "recent_disagreement_updates": [
                item.model_dump(exclude_none=True) for item in self.recent_disagreement_updates
            ],
            "unresolved_uncertainties": [
                item.model_dump(exclude_none=True) for item in self.unresolved_uncertainties
            ],
            "recent_reasoning_traces": [
                item.model_dump(exclude_none=True) for item in self.recent_reasoning_traces
            ],
            "planner_guidance": self.planner_guidance,
        }

    def merged_guidance_text(self) -> str | None:
        parts: list[str] = []
        if self.human_feedback:
            parts.append(self.human_feedback)
        parts.extend(self.evaluation_summary.key_findings[:2])
        parts.extend(item.summary for item in self.recent_disagreement_updates[:2])
        parts.extend(item.summary for item in self.recent_reasoning_traces[:2])
        parts.extend(item.content for item in self.recent_human_feedback[:2])
        parts.extend(item.question for item in self.unresolved_uncertainties[:2])
        parts.extend(self.planner_guidance[:2])
        return " ".join(part for part in parts if part) or None


class PlannerCandidateSupplement(ShadowBaseModel):
    proposal_id: str = Field(min_length=1)
    candidate: CandidateExperiment
    rationale: str = Field(min_length=1)
    source: str = Field(default="programmatic_planner", min_length=1)


class InterpretationEnhancement(ShadowBaseModel):
    enhancement_id: str = Field(min_length=1)
    target_hypothesis_id: str | None = None
    interpretation: str = Field(min_length=1)
    evidence_basis: list[str] = Field(default_factory=list)
    related_uncertainties: list[str] = Field(default_factory=list)
    suggested_state_note: str | None = None
    impact_direction: Literal["supports", "weakens", "clarifies"] = "clarifies"
    impact_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    uncertainty_priority_action: Literal["increase", "decrease", "maintain"] = "maintain"


class ProtocolRefinementSuggestion(ShadowBaseModel):
    suggestion_id: str = Field(min_length=1)
    target_candidate_id: str | None = None
    refinement_type: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    suggested_model_parameters: dict[str, Any] = Field(default_factory=dict)
    suggested_feature_focus: list[str] = Field(default_factory=list)
    suggested_steps: list[ExperimentStep] = Field(default_factory=list)
    protocol_notes: list[str] = Field(default_factory=list)


class ReasoningPlannerOutput(ShadowBaseModel):
    task_id: str = Field(min_length=1)
    source_round_id: int = Field(ge=0)
    next_round_id: int = Field(ge=0)
    source_experiment_id: str | None = None
    planner_mode: Literal["programmatic", "llm"] = "programmatic"
    candidate_supplements: list[PlannerCandidateSupplement] = Field(default_factory=list)
    interpretation_enhancements: list[InterpretationEnhancement] = Field(default_factory=list)
    protocol_refinements: list[ProtocolRefinementSuggestion] = Field(default_factory=list)
    summary: str | None = None
    generated_at: datetime = Field(default_factory=datetime.now)

    def to_experiment_planner_payload(self) -> dict[str, Any]:
        return {
            "candidate_supplements": [
                item.model_dump(exclude_none=True) for item in self.candidate_supplements
            ],
            "protocol_refinements": [
                item.model_dump(exclude_none=True) for item in self.protocol_refinements
            ],
            "summary": self.summary,
        }

    def to_scientific_interpreter_payload(self) -> dict[str, Any]:
        return {
            "interpretation_enhancements": [
                item.model_dump(exclude_none=True) for item in self.interpretation_enhancements
            ],
            "summary": self.summary,
        }


class UncertaintyState(ShadowBaseModel):
    task_id: str = Field(min_length=1)
    current_round: int = Field(ge=0)
    last_updated: datetime
    records: list[UncertaintyRecord] = Field(default_factory=list)
    priority_queue: UncertaintyPriorityQueue | None = None

    @field_validator("records")
    @classmethod
    def unique_uncertainty_ids(cls, value: list[UncertaintyRecord]) -> list[UncertaintyRecord]:
        ids = [item.uncertainty_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("UncertaintyState.records contains duplicate uncertainty_id")
        return value

    def record_index(self) -> dict[str, UncertaintyRecord]:
        return {item.uncertainty_id: item for item in self.records}


class ExperimentMemoryEntry(ShadowBaseModel):
    experiment_id: str = Field(min_length=1)
    round_id: int = Field(ge=0)
    status: ExecutionStatus
    tested_hypotheses: list[str] = Field(default_factory=list)
    protocol_path: str | None = None
    result_path: str | None = None
    evaluation_path: str | None = None
    metrics_snapshot: PerformanceMetrics | None = None
    key_findings: list[str] = Field(default_factory=list)
    visualizations: list[str] = Field(default_factory=list)
    reasoning_traces: list["ReasoningTraceEntry"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ReasoningTraceEntry(ShadowBaseModel):
    trace_id: str = Field(min_length=1)
    round_id: int = Field(ge=0)
    source: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    related_hypotheses: list[str] = Field(default_factory=list)
    related_uncertainties: list[str] = Field(default_factory=list)
    support_delta: float | None = Field(default=None, ge=-1.0, le=1.0)
    priority_delta: float | None = Field(default=None, ge=-1.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.now)


class ExperimentMemoryState(ShadowBaseModel):
    task_id: str = Field(min_length=1)
    current_round: int = Field(ge=0)
    last_updated: datetime
    entries: list[ExperimentMemoryEntry] = Field(default_factory=list)

    @field_validator("entries")
    @classmethod
    def unique_experiment_entries(cls, value: list[ExperimentMemoryEntry]) -> list[ExperimentMemoryEntry]:
        ids = [item.experiment_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("ExperimentMemoryState.entries contains duplicate experiment_id")
        return value

    def entry_index(self) -> dict[str, ExperimentMemoryEntry]:
        return {item.experiment_id: item for item in self.entries}


class ProcessStep(ShadowBaseModel):
    name: str = Field(min_length=1)
    status: StepStatus
    requires_user_approval: bool = False
    notes: str | None = None


class ProcessPhase(ShadowBaseModel):
    status: StepStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None
    steps: dict[str, ProcessStep] = Field(default_factory=dict)


class UserSettings(ShadowBaseModel):
    auto_continue: bool = False
    stop_at_each_step: bool = True
    approval_required: list[str] = Field(default_factory=list)


class UserRequests(ShadowBaseModel):
    stop_requested: bool = False
    stop_at_phase: str | None = None
    pause_reason: str | None = None


class ProcessState(ShadowBaseModel):
    task_id: str = Field(min_length=1)
    current_round: int = Field(ge=0)
    current_stage: str = Field(min_length=1)
    current_phase: str | None = None
    current_step: str | None = None
    progress_percentage: int | None = Field(default=None, ge=0, le=100)
    started_at: datetime
    phase_sequence: list[str] = Field(default_factory=list)
    phases: dict[str, ProcessPhase] = Field(default_factory=dict)
    steps: dict[str, ProcessStep] = Field(default_factory=dict)
    user_settings: UserSettings = Field(default_factory=UserSettings)
    user_requests: UserRequests = Field(default_factory=UserRequests)


class DecisionEntry(ShadowBaseModel):
    decision_id: str = Field(default_factory=lambda: f"D{int(datetime.now().timestamp() * 1000)}", min_length=1)
    timestamp: datetime
    round_id: int | None = Field(default=None, ge=0)
    phase: str | None = None
    step: str | None = None
    decision_type: DecisionType
    made_by: Literal["human_pi", "system"]
    summary: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class HumanFeedbackEntry(ShadowBaseModel):
    feedback_id: str = Field(min_length=1)
    timestamp: datetime
    phase: str = Field(min_length=1)
    round_number: int = Field(ge=0)
    feedback_type: str = Field(min_length=1)
    content: str = Field(min_length=1)
    implemented_in_round: int | None = Field(default=None, ge=0)
    status: str = Field(default="recorded", min_length=1)
    related_experiment_id: str | None = None
    linked_reasoning_trace_ids: list[str] = Field(default_factory=list)
    context_summary: str | None = None


class StopHistoryEntry(ShadowBaseModel):
    stop_id: str = Field(min_length=1)
    timestamp: datetime
    type: Literal["pause", "stop"]
    phase: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    resumed_at: datetime | None = None


class DecisionLog(ShadowBaseModel):
    schema_version: str = "1.0"
    message_type: Literal["decision_log"] = "decision_log"
    task_id: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=datetime.now)
    decisions: list[DecisionEntry] = Field(default_factory=list)
    human_feedback: list[HumanFeedbackEntry] = Field(default_factory=list)
    stop_history: list[StopHistoryEntry] = Field(default_factory=list)
