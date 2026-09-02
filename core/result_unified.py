from __future__ import annotations

import json
from pathlib import Path

from core.unified_schema import (
    ExecutionSummary,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentRun,
    MetricDelta,
    RunMetrics,
    VisualizationArtifact,
)


def build_run_metrics(raw_metrics: dict) -> RunMetrics:
    return RunMetrics(
        rmse=raw_metrics.get("test_rmse"),
        mae=raw_metrics.get("test_mae"),
        pearson_r=raw_metrics.get("test_pearson_r"),
        r2=raw_metrics.get("test_r2"),
    )


def build_metric_delta(baseline_metrics: dict, treatment_metrics: dict) -> MetricDelta:
    return MetricDelta(
        rmse=_safe_delta(treatment_metrics.get("test_rmse"), baseline_metrics.get("test_rmse")),
        mae=_safe_delta(treatment_metrics.get("test_mae"), baseline_metrics.get("test_mae")),
        pearson_r=_safe_delta(treatment_metrics.get("test_pearson_r"), baseline_metrics.get("test_pearson_r")),
        r2=_safe_delta(treatment_metrics.get("test_r2"), baseline_metrics.get("test_r2")),
    )


def build_experiment_result(
    protocol: ExperimentProtocol,
    *,
    baseline_output: dict,
    treatment_output: dict,
    prediction_paths: dict[str, str | Path],
    visualizations: list[VisualizationArtifact],
    duration_seconds: float,
) -> ExperimentResult:
    baseline_metrics = baseline_output["metrics"]
    treatment_metrics = treatment_output["metrics"]

    return ExperimentResult(
        experiment_id=protocol.experiment_id,
        round_id=protocol.round_id,
        status="completed",
        runs=[
            ExperimentRun(
                run_id="baseline",
                name="baseline",
                prediction_artifact=str(prediction_paths["baseline"]),
                metrics=build_run_metrics(baseline_metrics),
            ),
            ExperimentRun(
                run_id="treatment",
                name="treatment",
                prediction_artifact=str(prediction_paths["treatment"]),
                metrics=build_run_metrics(treatment_metrics),
            ),
        ],
        comparison=build_metric_delta(baseline_metrics, treatment_metrics),
        visualizations=visualizations,
        execution=ExecutionSummary(
            duration_seconds=duration_seconds,
            compute_seconds=duration_seconds,
            status="completed",
        ),
    )


def export_result_bundle(
    result: ExperimentResult,
    protocol: ExperimentProtocol,
    *,
    round_dir: Path,
    latest_protocol_path: Path,
    latest_metrics_path: Path,
) -> None:
    round_dir.mkdir(parents=True, exist_ok=True)
    latest_protocol_path.parent.mkdir(parents=True, exist_ok=True)
    latest_metrics_path.parent.mkdir(parents=True, exist_ok=True)

    protocol_payload = protocol.model_dump(mode="json", exclude_none=True)
    result_payload = result.model_dump(mode="json", exclude_none=True)
    latest_metrics_payload = {
        "experiment_id": result.experiment_id,
        "round_id": result.round_id,
        "comparison": result.comparison.model_dump(exclude_none=True),
        "baseline": result.runs[0].metrics.model_dump(exclude_none=True),
        "treatment": result.runs[1].metrics.model_dump(exclude_none=True),
    }

    (round_dir / "protocol.json").write_text(
        json.dumps(protocol_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (round_dir / "result_unified.json").write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    latest_protocol_path.write_text(
        json.dumps(protocol_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    latest_metrics_path.write_text(
        json.dumps(latest_metrics_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _safe_delta(new_value: float | None, old_value: float | None) -> float | None:
    if new_value is None or old_value is None:
        return None
    return float(new_value) - float(old_value)
