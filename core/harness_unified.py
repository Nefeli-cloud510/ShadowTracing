from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from core.protocol_bridge import ElasticNetDataSourceConfig, ElasticNetProtocolBridge
from core.result_unified import build_experiment_result, export_result_bundle
from core.unified_schema import ExperimentProtocol, ExperimentResult, VisualizationArtifact
from models import elasticnet_runner as runner


class UnifiedExperimentHarness:
    """Type-safe harness that executes the real ElasticNet runner via unified schemas."""

    def __init__(
        self,
        *,
        data_source: ElasticNetDataSourceConfig,
        project_root: Path | None = None,
        run_shap: bool = True,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parent.parent
        self.results_dir = self.project_root / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.latest_protocol_path = self.project_root / "config" / "latest_protocol.json"
        self.latest_metrics_path = self.project_root / "outputs" / "latest_metrics.json"
        self.bridge = ElasticNetProtocolBridge(data_source)
        self.run_shap = run_shap

    def run(self, protocol: ExperimentProtocol) -> ExperimentResult:
        if protocol.model.name.lower() != "elasticnet":
            raise ValueError(f"当前统一 harness 仅支持 ElasticNet，收到: {protocol.model.name}")
        if not protocol.features.treatment:
            raise ValueError("ExperimentProtocol.features.treatment 不能为空")
        is_baseline_single_arm = "experiment_mode:baseline_single_arm" in (protocol.notes or []) or not protocol.features.control
        if not is_baseline_single_arm and not protocol.features.control:
            raise ValueError("ExperimentProtocol.features.control 不能为空")

        round_dir = self.results_dir / f"round_{protocol.round_id:02d}"
        execution_dir = round_dir / protocol.experiment_id
        execution_dir.mkdir(parents=True, exist_ok=True)

        started = time.perf_counter()
        baseline_features = self._resolve_feature_columns(
            protocol=protocol,
            label="baseline",
            fallback=protocol.features.treatment if is_baseline_single_arm else protocol.features.control,
        )
        treatment_features = self._resolve_feature_columns(
            protocol=protocol,
            label="treatment",
            fallback=protocol.features.treatment,
        )
        if is_baseline_single_arm:
            baseline_output = self._execute_variant(
                protocol=protocol,
                feature_columns=baseline_features,
                label="baseline",
                output_dir=execution_dir / "baseline",
            )
            treatment_output = baseline_output
        else:
            baseline_output = self._execute_variant(
                protocol=protocol,
                feature_columns=baseline_features,
                label="baseline",
                output_dir=execution_dir / "baseline",
            )
            treatment_output = self._execute_variant(
                protocol=protocol,
                feature_columns=treatment_features,
                label="treatment",
                output_dir=execution_dir / "treatment",
            )
        duration_seconds = time.perf_counter() - started

        predictions_dir = execution_dir / "predictions"
        predictions_dir.mkdir(parents=True, exist_ok=True)
        prediction_paths = {
            "baseline": self._to_relative_path(self._write_prediction_csv(
                predictions_dir / f"{protocol.experiment_id}_baseline.csv",
                baseline_output,
            )),
            "treatment": self._to_relative_path(self._write_prediction_csv(
                predictions_dir / f"{protocol.experiment_id}_treatment.csv",
                treatment_output,
            )),
        }

        visualizations = self._collect_visualizations(protocol, baseline_output, treatment_output)
        result = build_experiment_result(
            protocol,
            baseline_output=baseline_output,
            treatment_output=treatment_output,
            prediction_paths=prediction_paths,
            visualizations=visualizations,
            duration_seconds=duration_seconds,
        )
        export_result_bundle(
            result,
            protocol,
            round_dir=round_dir,
            latest_protocol_path=self.latest_protocol_path,
            latest_metrics_path=self.latest_metrics_path,
        )
        return result

    @staticmethod
    def _resolve_feature_columns(
        *,
        protocol: ExperimentProtocol,
        label: str,
        fallback: list[str],
    ) -> list[str]:
        feature_groups = protocol.model.parameters.get("feature_groups")
        if isinstance(feature_groups, dict):
            configured = feature_groups.get(label)
            if isinstance(configured, list):
                normalized = [str(item).strip() for item in configured if str(item).strip()]
                if normalized:
                    return normalized
        return [str(item).strip() for item in fallback if str(item).strip()]

    def _execute_variant(
        self,
        *,
        protocol: ExperimentProtocol,
        feature_columns: list[str],
        label: str,
        output_dir: Path,
    ) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        runner_config = self.bridge.build_runner_config(protocol, feature_columns)

        x_raw, y_raw, time_raw = runner.load_and_merge_data(runner_config)
        x_all, y_all, time_all, feature_names = runner.build_sliding_window(
            x_raw,
            y_raw,
            time_raw,
            runner_config.time_window_config,
        )
        xtr, xte, ytr, yte, time_train, time_test, scaler = runner.split_and_scale_dataset(
            x_all,
            y_all,
            time_all,
            runner_config.time_window_config.test_split_ratio,
            feature_names,
        )

        model = runner.train_elasticnet_model(xtr, ytr, runner_config.elasticnet_config)
        metrics, ytr_pred, yte_pred = runner.evaluate_model(model, xtr, xte, ytr, yte)
        coef_df = runner.make_coefficient_table(model, feature_names)
        coef_df.to_csv(output_dir / f"{label}_coefficients.csv", index=False, encoding="utf-8-sig")

        figure_paths = {
            "coefficients": runner.plot_feature_coefficients(coef_df, output_dir),
            "scatter": runner.plot_prediction_scatter(yte, yte_pred, metrics, output_dir),
            "timeseries": runner.plot_prediction_series(time_test, yte, yte_pred, output_dir),
            "residual_scatter": runner.plot_residual_scatter(yte_pred, yte - yte_pred, output_dir),
            "residual_hist": runner.plot_residual_histogram(yte - yte_pred, output_dir),
        }

        shap_paths: dict[str, str] = {}
        shap_importance = None
        if self.run_shap:
            shap_result = runner.run_shap_analysis(model, xtr, xte, output_dir)
            shap_importance = shap_result["importance"]
            shap_paths = {
                "summary": str(shap_result["summary_path"]),
                "bar": str(shap_result["bar_path"]),
                "waterfall": str(shap_result["waterfall_path"]),
                "importance_csv": str(shap_result["importance_path"]),
            }

        return {
            "label": label,
            "config": runner_config.model_dump(mode="json"),
            "metrics": metrics,
            "coefficients": coef_df,
            "model": model,
            "scaler": scaler,
            "time_train": time_train,
            "time_test": time_test,
            "y_train": ytr,
            "y_test": yte,
            "y_train_pred": ytr_pred,
            "y_test_pred": yte_pred,
            "figure_paths": {name: str(path) for name, path in figure_paths.items()},
            "shap_paths": shap_paths,
            "shap_importance": shap_importance,
        }

    @staticmethod
    def _write_prediction_csv(file_path: Path, execution_output: dict) -> Path:
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(execution_output["time_test"]).astype(str),
                "y_true": execution_output["y_test"],
                "y_pred": execution_output["y_test_pred"],
            }
        )
        frame.to_csv(file_path, index=False, encoding="utf-8-sig")
        return file_path

    def _collect_visualizations(
        self,
        protocol: ExperimentProtocol,
        baseline_output: dict,
        treatment_output: dict,
    ) -> list[VisualizationArtifact]:
        visualizations: list[VisualizationArtifact] = []

        for label, output in (("baseline", baseline_output), ("treatment", treatment_output)):
            for name, path in output["figure_paths"].items():
                visualizations.append(
                    VisualizationArtifact(
                        name=f"{protocol.experiment_id}_{label}_{name}",
                        path=self._to_relative_path(Path(path)),
                    )
                )
            for name, path in output["shap_paths"].items():
                visualizations.append(
                    VisualizationArtifact(
                        name=f"{protocol.experiment_id}_{label}_shap_{name}",
                        path=self._to_relative_path(Path(path)),
                    )
                )

        return visualizations

    def _to_relative_path(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.project_root.resolve())
            return relative.as_posix()
        except ValueError:
            return path.as_posix()
