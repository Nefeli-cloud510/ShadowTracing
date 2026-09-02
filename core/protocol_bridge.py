from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from core.schema import ExperimentConfig as LegacyAdjustmentConfig
from core.unified_schema import ExperimentProtocol, ModelSpec, ShadowBaseModel
from models.elasticnet_runner import (
    ElasticNetConfig as RunnerElasticNetConfig,
    ExperimentConfig as RunnerExperimentConfig,
    FileConfig as RunnerFileConfig,
    TimeWindowConfig as RunnerTimeWindowConfig,
)


class ElasticNetDataSourceConfig(ShadowBaseModel):
    """Static data binding needed by the real ElasticNet runner."""

    omni_file_path: Path
    lhaaso_file_path: Path
    time_column: str = "TIME"
    target_column: str = "SW Plasma Speed, km/s"
    test_split_ratio: float = 0.2
    random_state: int = 42


class ElasticNetProtocolBridge:
    """Convert unified experiment protocols into the runner's config schema."""

    def __init__(self, data_source: ElasticNetDataSourceConfig) -> None:
        self.data_source = data_source

    def validate_feature_columns(self, feature_columns: Iterable[str]) -> None:
        feature_list = list(dict.fromkeys(feature_columns))
        if not feature_list:
            raise ValueError("feature_columns cannot be empty")

        omni_columns = set(self._read_columns(self.data_source.omni_file_path))
        lhaaso_columns = set(self._read_columns(self.data_source.lhaaso_file_path))
        available_columns = omni_columns | lhaaso_columns
        missing = [name for name in feature_list if name not in available_columns]
        if missing:
            raise KeyError(f"特征列在数据源中不存在: {missing}")

    def build_runner_config(self, protocol: ExperimentProtocol, feature_columns: list[str]) -> RunnerExperimentConfig:
        self.validate_feature_columns(feature_columns)
        model_parameters = protocol.model.parameters

        return RunnerExperimentConfig(
            file_config=RunnerFileConfig(
                omni_file_path=self.data_source.omni_file_path,
                lhaaso_file_path=self.data_source.lhaaso_file_path,
                time_column=self.data_source.time_column,
                target_column=self.data_source.target_column or protocol.target,
                feature_columns=feature_columns,
            ),
            time_window_config=RunnerTimeWindowConfig(
                window_size=int(model_parameters.get("window_size", 3)),
                test_split_ratio=float(model_parameters.get("test_split_ratio", self.data_source.test_split_ratio)),
                use_lag_feature=bool(model_parameters.get("use_lag_feature", False)),
                max_lag_day=int(model_parameters.get("max_lag_day", 0)),
            ),
            elasticnet_config=RunnerElasticNetConfig(
                alpha=float(model_parameters.get("alpha", 0.5)),
                l1_ratio=float(model_parameters.get("l1_ratio", 0.5)),
                random_state=int(model_parameters.get("random_state", self.data_source.random_state)),
            ),
        )

    @staticmethod
    def _read_columns(path: Path) -> list[str]:
        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path, nrows=0).columns.tolist()
        if suffix in {".csv", ".txt"}:
            return pd.read_csv(path, sep=r"\s+|,", engine="python", nrows=0).columns.tolist()
        raise ValueError(f"暂不支持的数据格式: {path}")


def legacy_config_to_protocol(
    config: LegacyAdjustmentConfig,
    *,
    round_id: int,
    task_id: str,
    target: str,
    control_features: list[str],
    treatment_features: list[str],
    experiment_id: str = "LEGACY_E01",
) -> ExperimentProtocol:
    """Adapt the old minimal config into the unified protocol format."""

    model_parameters = config.model_dump(exclude={"reasoning"})
    model_parameters["random_state"] = 42
    model_parameters["test_split_ratio"] = 0.2

    return ExperimentProtocol(
        experiment_id=experiment_id,
        round_id=round_id,
        task_id=task_id,
        target=target,
        features={
            "target": target,
            "control": control_features,
            "treatment": treatment_features,
            "lags": {},
        },
        model=ModelSpec(
            name="ElasticNet",
            parameters=model_parameters,
        ),
        notes=[config.reasoning] if config.reasoning else [],
    )
