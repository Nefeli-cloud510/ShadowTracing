from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd
from pydantic import Field

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
    extra_file_paths: list[Path] = []
    sparse_sources: list[str] = Field(default_factory=list, description="需要缺失记录剔除审计的源名称")
    time_column: str = "TIME"
    target_column: str = "SW Plasma Speed, km/s"
    column_aliases: dict[str, str] = {}
    test_split_ratio: float = 0.2
    random_state: int = 42


class ElasticNetProtocolBridge:
    """Convert unified experiment protocols into the runner's config schema."""

    def __init__(self, data_source: ElasticNetDataSourceConfig) -> None:
        self.data_source = data_source

    def validate_feature_columns(self, feature_columns: Iterable[str]) -> list[str]:
        feature_list = list(dict.fromkeys(feature_columns))
        if not feature_list:
            raise ValueError("feature_columns cannot be empty")

        available_columns = self._available_columns()
        valid_columns: list[str] = []
        for name in feature_list:
            resolved = self._resolve_column_name(name, available_columns)
            if resolved is not None and resolved not in valid_columns:
                valid_columns.append(resolved)
        if not valid_columns:
            missing = [name for name in feature_list if self._resolve_column_name(name, available_columns) is None]
            raise KeyError(f"特征列在数据源中不存在: {missing}")
        return valid_columns

    def build_runner_config(
        self,
        protocol: ExperimentProtocol,
        feature_columns: list[str],
        arm_overrides: dict | None = None,
    ) -> RunnerExperimentConfig:
        feature_columns = self.validate_feature_columns(feature_columns)
        model_parameters = protocol.model.parameters
        available_columns = self._available_columns()
        target_column = self._resolve_column_name(self.data_source.target_column or protocol.target, available_columns) or protocol.target
        overrides = arm_overrides or {}
        window_size = int(overrides.get("window_size", model_parameters.get("window_size", 3)))
        forecast_horizon_days = int(
            overrides.get(
                "forecast_horizon_days",
                model_parameters.get("forecast_horizon_days", 0),
            )
        )
        past_lag_days = overrides.get("past_lag_days", model_parameters.get("past_lag_days"))

        return RunnerExperimentConfig(
            file_config=RunnerFileConfig(
                omni_file_path=self.data_source.omni_file_path,
                lhaaso_file_path=self.data_source.lhaaso_file_path,
                extra_file_paths=self.data_source.extra_file_paths,
                time_column=self.data_source.time_column,
                target_column=target_column,
                feature_columns=feature_columns,
                sparse_sources=self.data_source.sparse_sources,
            ),
            time_window_config=RunnerTimeWindowConfig(
                window_size=window_size,
                test_split_ratio=float(model_parameters.get("test_split_ratio", self.data_source.test_split_ratio)),
                use_lag_feature=bool(model_parameters.get("use_lag_feature", False)),
                max_lag_day=int(model_parameters.get("max_lag_day", 0)),
                forecast_horizon_days=forecast_horizon_days,
                past_lag_days=int(past_lag_days) if past_lag_days is not None else None,
            ),
            elasticnet_config=RunnerElasticNetConfig(
                alpha=float(model_parameters.get("alpha", 0.5)),
                l1_ratio=float(model_parameters.get("l1_ratio", 0.5)),
                random_state=int(model_parameters.get("random_state", self.data_source.random_state)),
            ),
        )

    def _available_columns(self) -> set[str]:
        paths = [self.data_source.omni_file_path, self.data_source.lhaaso_file_path, *self.data_source.extra_file_paths]
        available_columns: set[str] = set()
        for path in paths:
            available_columns.update(self._read_columns(path))
        return available_columns

    def _resolve_column_name(self, name: str | None, available_columns: set[str]) -> str | None:
        if not name:
            return None
        if name in available_columns:
            return name
        alias = self.data_source.column_aliases.get(name)
        if alias and alias in available_columns:
            return alias
        return None

    @staticmethod
    def _read_columns(path: Path) -> list[str]:
        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path, nrows=0).columns.tolist()
        if suffix == ".csv":
            return pd.read_csv(path, nrows=0).columns.tolist()
        if suffix == ".txt":
            return pd.read_csv(path, sep=r"\s+", engine="python", nrows=0).columns.tolist()
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
