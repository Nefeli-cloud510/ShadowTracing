import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import shap
from pydantic import BaseModel, Field, ValidationError
from sklearn.linear_model import ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
plt.switch_backend("Agg")


# 输入配置校验

class FileConfig(BaseModel):
    omni_file_path: Path
    lhaaso_file_path: Path
    extra_file_paths: List[Path] = []
    time_column: str
    target_column: str
    feature_columns: List[str]
    sparse_sources: List[str] = Field(default_factory=list, description="需要缺失记录剔除审计的源名称")

    def model_post_init(self, __context):
        if not self.omni_file_path.exists():
            raise FileNotFoundError(f"OMNI文件不存在 {self.omni_file_path}")
        if not self.lhaaso_file_path.exists():
            raise FileNotFoundError(f"LHAASO文件不存在 {self.lhaaso_file_path}")
        for path in self.extra_file_paths:
            if not path.exists():
                raise FileNotFoundError(f"额外数据文件不存在 {path}")

class TimeWindowConfig(BaseModel):
    window_size: int = Field(ge=1, le=196, description="滑动窗口天数，1~196")
    test_split_ratio: float = Field(ge=0.1, le=0.5)
    use_lag_feature: bool
    max_lag_day: int = Field(ge=0, le=10)
    forecast_horizon_days: int = Field(default=0, ge=0, le=30, description="预测超前天数，0 表示同天")
    past_lag_days: int | None = Field(default=None, ge=1, le=196, description="仅保留最近 N 天滞后特征")

class ElasticNetConfig(BaseModel):
    alpha: float
    l1_ratio: float
    random_state: int

class ExperimentConfig(BaseModel):
    file_config: FileConfig
    time_window_config: TimeWindowConfig
    elasticnet_config: ElasticNetConfig


@dataclass
class DataCoverageReport:
    """单个数据源的日历覆盖统计。"""

    source: str
    expected_days: int = 0
    observed_days: int = 0
    missing_days: int = 0
    coverage_ratio: float = 1.0
    interpolated_days: int = 0
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "expected_days": self.expected_days,
            "observed_days": self.observed_days,
            "missing_days": self.missing_days,
            "coverage_ratio": self.coverage_ratio,
            "interpolated_days": self.interpolated_days,
            "note": self.note,
        }


@dataclass
class MergedLoadResult:
    """数据合并结果，附带来源覆盖与稀疏源识别信息。"""

    X: pd.DataFrame
    y: pd.Series
    time: pd.Series
    coverage: list[DataCoverageReport]
    active_sparse_sources: list[str]
    merged_sources: list[str]


@dataclass
class SlidingWindowResult:
    """滑动窗口构造结果。窗口直接基于合并后剩余行构造。"""

    X_all: np.ndarray
    y_all: np.ndarray
    time_all: np.ndarray
    feature_names: list[str]
    dropped_gap_windows: int = 0
    total_windows: int = 0

def load_llm_json_config(json_path: str | Path) -> ExperimentConfig:
    try:
        json_path = Path(json_path)
        raw_config = json_path.read_text(encoding="utf-8")
        config_dict = json.loads(raw_config)
        return ExperimentConfig.model_validate(config_dict)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"配置文件不存在: {json_path}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"配置文件不是合法JSON: {e}") from e
    except ValidationError as e:
        raise ValueError(f"LLM输出配置校验失败: {e}") from e
    

    # 数据读取与合并

def _read_table(file_path: Path) -> pd.DataFrame:
    suffix = file_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(file_path)
    if suffix == ".csv":
        return pd.read_csv(file_path)
    if suffix == ".txt":
        return pd.read_csv(file_path, sep=r"\s+", engine="python")
    raise ValueError(f"暂不支持的文件格式: {file_path}")

def _normalize_time_column(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        normalized = pd.to_datetime(series, errors="coerce")
    else:
        cleaned = series.astype(str).str.replace(r"_x000d_", "", regex=True).str.strip()
        yyyymmdd = cleaned.str.extract(r"(\d{8})", expand=False)
        normalized = pd.to_datetime(yyyymmdd, format="%Y%m%d", errors="coerce")
        if normalized.isna().all():
            normalized = pd.to_datetime(cleaned, errors="coerce")

    if normalized.isna().any():
        bad_values = series[normalized.isna()].head(5).tolist()
        raise ValueError(f"TIME列存在无法解析的日期值: {bad_values}")
    return normalized

def load_and_merge_data(cfg: ExperimentConfig) -> MergedLoadResult:
    file_cfg = cfg.file_config
    unique_sources: list[tuple[str, Path]] = []
    seen_paths: set[str] = set()
    for path in [
        file_cfg.omni_file_path,
        file_cfg.lhaaso_file_path,
        *file_cfg.extra_file_paths,
    ]:
        resolved = str(path.resolve())
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        unique_sources.append((path.stem, path))
    data_frames = [(label, _read_table(path)) for label, path in unique_sources]

    normalized_frames: list[pd.DataFrame] = []
    for label, frame in data_frames:
        if file_cfg.time_column not in frame.columns:
            raise KeyError(f"{label}数据缺少时间列: {file_cfg.time_column}")
        next_frame = frame.copy()
        next_frame[file_cfg.time_column] = _normalize_time_column(next_frame[file_cfg.time_column])
        normalized_frames.append(next_frame)

    source_index = {label: idx for idx, (label, _) in enumerate(data_frames)}
    source_columns = {
        label: set(normalized_frames[idx].columns)
        for label, idx in source_index.items()
    }

    # 只合并当前实验臂实际使用到的源：目标列来源 + 特征列来源。
    required_labels: set[str] = set()
    target_sources = [
        label for label, idx in source_index.items()
        if file_cfg.target_column in source_columns[label]
    ]
    if not target_sources:
        raise KeyError(f"没有任何数据源包含目标列: {file_cfg.target_column}")
    required_labels.update(target_sources)
    for col in file_cfg.feature_columns:
        matches = [label for label, idx in source_index.items() if col in source_columns[label]]
        required_labels.update(matches)

    ordered_sources = [
        label for label, _ in unique_sources if label in required_labels
    ]
    if not ordered_sources:
        raise KeyError("没有可用的数据源")

    # 期望日历范围只按本轮实际参与合并的源计算，未使用的文件（例如本轮未用到
    # 的 PFSS）既不参与合并，也不该把其缺失天数计入覆盖率审计。
    ordered_dates: set[pd.Timestamp] = set()
    for label in ordered_sources:
        frame = normalized_frames[source_index[label]]
        ordered_dates.update(
            pd.to_datetime(frame[file_cfg.time_column]).dt.normalize().unique()
        )
    if not ordered_dates:
        raise ValueError("本轮使用的数据源均为空，无法确定日历范围")
    expected_days = int((max(ordered_dates) - min(ordered_dates)).days + 1)

    # 先构造覆盖报告，再按需合并。
    coverage_reports: list[DataCoverageReport] = []
    for label in ordered_sources:
        frame = normalized_frames[source_index[label]]
        observed_dates = pd.to_datetime(frame[file_cfg.time_column]).dt.normalize().unique()
        observed_days = int(len(observed_dates))
        missing_days = max(0, expected_days - observed_days)
        coverage_ratio = observed_days / expected_days if expected_days else 1.0
        coverage_reports.append(
            DataCoverageReport(
                source=label,
                expected_days=expected_days,
                observed_days=observed_days,
                missing_days=missing_days,
                coverage_ratio=round(coverage_ratio, 6),
                note="缺失记录将按行剔除" if missing_days else None,
            )
        )

    configured_sparse = set(file_cfg.sparse_sources)
    # sparse_sources 为空代表本轮未显式启用任一稀疏源的缺失记录审计；只有配置了
    # 源名称（且该源确有缺失日）才可能启用，不能让“未配置”退化成全员启用。
    active_sparse_sources = (
        [
            report.source
            for report in coverage_reports
            if report.missing_days > 0 and report.source in configured_sparse
        ]
        if configured_sparse
        else []
    )

    df_merge = normalized_frames[source_index[ordered_sources[0]]]
    for label in ordered_sources[1:]:
        df_merge = pd.merge(
            df_merge,
            normalized_frames[source_index[label]],
            on=file_cfg.time_column,
            how="inner",
        )

    missing_features = [col for col in file_cfg.feature_columns if col not in df_merge.columns]
    if missing_features:
        raise KeyError(f"合并后的数据缺少特征列: {missing_features}")
    if file_cfg.target_column not in df_merge.columns:
        raise KeyError(f"合并后的数据缺少目标列: {file_cfg.target_column}")

    selected_columns = file_cfg.feature_columns + [file_cfg.target_column]
    df_merge = (
        df_merge
        .sort_values(file_cfg.time_column)
        .dropna(subset=selected_columns)
        .reset_index(drop=True)
    )

    X = df_merge[file_cfg.feature_columns].astype(float).copy()
    y = df_merge[file_cfg.target_column].astype(float).copy()
    time_raw = df_merge[file_cfg.time_column].copy()
    print(
        f"数据合并完成，有效样本数: {len(df_merge)}；"
        f"缺失记录审计源: {active_sparse_sources or '无'}"
    )
    return MergedLoadResult(
        X=X,
        y=y,
        time=time_raw,
        coverage=coverage_reports,
        active_sparse_sources=active_sparse_sources,
        merged_sources=ordered_sources,
    )


# 时间窗构造与数据集切分

def build_sliding_window(
    X_raw: pd.DataFrame,
    y_raw: pd.Series,
    time_raw: pd.Series,
    tw_cfg: TimeWindowConfig,
) -> SlidingWindowResult:
    window_size = tw_cfg.window_size
    forecast_horizon = tw_cfg.forecast_horizon_days
    past_lag_days = tw_cfg.past_lag_days or window_size
    if len(X_raw) <= window_size + forecast_horizon:
        raise ValueError(f"有效样本数 {len(X_raw)} 小于窗口大小 {window_size} 加超前天数 {forecast_horizon}")

    arr_x = X_raw.to_numpy(dtype=float)
    arr_y = y_raw.to_numpy(dtype=float)
    arr_t = pd.to_datetime(time_raw).to_numpy()

    X_all, y_all, time_all = [], [], []
    dropped_gap_windows = 0
    total_windows = 0
    feature_names = []
    for lag in range(past_lag_days, 0, -1):
        for col in X_raw.columns:
            feature_names.append(f"{col}_t-{lag}")

    for i in range(window_size, len(arr_x) - forecast_horizon):
        total_windows += 1
        X_all.append(arr_x[i - past_lag_days:i, :].reshape(-1))
        y_all.append(arr_y[i + forecast_horizon])
        time_all.append(arr_t[i + forecast_horizon])

    return SlidingWindowResult(
        X_all=np.asarray(X_all),
        y_all=np.asarray(y_all),
        time_all=np.asarray(time_all),
        feature_names=feature_names,
        dropped_gap_windows=dropped_gap_windows,
        total_windows=total_windows,
    )

def split_and_scale_dataset(X_all: np.ndarray, y_all: np.ndarray, time_all: np.ndarray, test_rate: float, feature_names: List[str]):
    split_idx = int(len(X_all) * (1 - test_rate))
    if split_idx <= 0 or split_idx >= len(X_all):
        raise ValueError("测试集比例导致训练集或测试集为空")

    Xtr = X_all[:split_idx]
    Xte = X_all[split_idx:]
    ytr = y_all[:split_idx]
    yte = y_all[split_idx:]
    ttr = time_all[:split_idx]
    tte = time_all[split_idx:]

    scaler = StandardScaler()
    Xtr_scaled = scaler.fit_transform(Xtr)
    Xte_scaled = scaler.transform(Xte)

    Xtr_df = pd.DataFrame(Xtr_scaled, columns=feature_names)
    Xte_df = pd.DataFrame(Xte_scaled, columns=feature_names)
    return Xtr_df, Xte_df, ytr, yte, ttr, tte, scaler


# 模型训练与评估

def train_elasticnet_model(Xtr: pd.DataFrame, ytr: np.ndarray, enet_cfg: ElasticNetConfig) -> ElasticNet:
    model = ElasticNet(
        alpha=enet_cfg.alpha,
        l1_ratio=enet_cfg.l1_ratio,
        random_state=enet_cfg.random_state,
        max_iter=10000
    )
    model.fit(Xtr, ytr)
    return model

def evaluate_model(model: ElasticNet, Xtr: pd.DataFrame, Xte: pd.DataFrame, ytr: np.ndarray, yte: np.ndarray):
    ytr_pred = model.predict(Xtr)
    yte_pred = model.predict(Xte)
    baseline_pred = np.full_like(yte, ytr.mean(), dtype=float)
    pearson_r = float(np.corrcoef(yte, yte_pred)[0, 1]) if len(yte) > 1 else float("nan")

    metrics = {
        "train_rmse": float(np.sqrt(mean_squared_error(ytr, ytr_pred))),
        "test_rmse": float(np.sqrt(mean_squared_error(yte, yte_pred))),
        "train_mae": float(mean_absolute_error(ytr, ytr_pred)),
        "test_mae": float(mean_absolute_error(yte, yte_pred)),
        "train_r2": float(r2_score(ytr, ytr_pred)),
        "test_r2": float(r2_score(yte, yte_pred)),
        "test_pearson_r": pearson_r,
        "baseline_test_rmse": float(np.sqrt(mean_squared_error(yte, baseline_pred)))
    }
    return metrics, ytr_pred, yte_pred

def make_coefficient_table(model: ElasticNet, feat_names: List[str]) -> pd.DataFrame:
    coef_df = pd.DataFrame({
        "feature": feat_names,
        "coefficient": model.coef_
    })
    coef_df["abs_coefficient"] = coef_df["coefficient"].abs()
    return coef_df.sort_values("abs_coefficient", ascending=False).reset_index(drop=True)


# 图表与残差分析

def plot_feature_coefficients(coef_df: pd.DataFrame, output_dir: Path, top_n: int = 15):
    plot_df = coef_df.head(top_n).sort_values("coefficient")
    plt.figure(figsize=(10, 6), dpi=300)
    colors = ["#c0392b" if v < 0 else "#2980b9" for v in plot_df["coefficient"]]
    plt.barh(plot_df["feature"], plot_df["coefficient"], color=colors)
    plt.xlabel("Coefficient")
    plt.ylabel("Feature")
    plt.title("ElasticNet Coefficients")
    plt.tight_layout()
    save_path = output_dir / "elasticnet_coefficients.png"
    plt.savefig(save_path, bbox_inches="tight")
    plt.close()
    return save_path

def plot_prediction_scatter(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    metrics: dict,
    output_dir: Path,
    *,
    experiment_label: str = "",
    train_true: np.ndarray | None = None,
    train_pred: np.ndarray | None = None,
):
    min_val = min(float(np.min(y_true)), float(np.min(y_pred)))
    max_val = max(float(np.max(y_true)), float(np.max(y_pred)))
    if train_true is not None and train_pred is not None and len(train_true) > 0:
        min_val = min(min_val, float(np.min(train_true)), float(np.min(train_pred)))
        max_val = max(max_val, float(np.max(train_true)), float(np.max(train_pred)))
    plt.figure(figsize=(7, 6), dpi=300)
    if train_true is not None and train_pred is not None and len(train_true) > 0:
        plt.scatter(train_true, train_pred, alpha=0.32, s=16, c="#8aa5c2", label="Train")
    plt.scatter(y_true, y_pred, alpha=0.7, s=26, c="#2c3e50")
    plt.plot([min_val, max_val], [min_val, max_val], "r--", lw=2)
    text_info = (
        f"R2 = {metrics['test_r2']:.3f}\n"
        f"RMSE = {metrics['test_rmse']:.2f}\n"
        f"r = {metrics['test_pearson_r']:.3f}"
    )
    plt.text(0.03, 0.97, text_info, transform=plt.gca().transAxes, va="top", bbox=dict(boxstyle="round", fc="white", alpha=0.8))
    plt.xlabel("True Solar-Wind Speed (km/s)")
    plt.ylabel("Predicted Solar-Wind Speed (km/s)")
    title = f"{experiment_label} True vs Predicted Scatter" if experiment_label else "True vs Predicted Scatter"
    plt.title(title)
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_path = output_dir / "elasticnet_scatter.png"
    plt.savefig(save_path, bbox_inches="tight")
    plt.close()
    return save_path

def plot_prediction_series(
    time_test: np.ndarray,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    output_dir: Path,
    *,
    experiment_label: str = "",
    time_train: np.ndarray | None = None,
    train_true: np.ndarray | None = None,
    train_pred: np.ndarray | None = None,
    x_limits: tuple | None = None,
    split_time=None,
):
    plt.figure(figsize=(9.25, 5), dpi=300)
    ax = plt.gca()
    if time_train is not None and train_true is not None and train_pred is not None and len(time_train) > 0:
        ax.plot(
            time_train,
            train_true,
            linestyle="-",
            linewidth=1.2,
            alpha=0.7,
            color="#7f9ab3",
            label="True (Train)",
        )
        ax.plot(
            time_train,
            train_pred,
            linestyle="-",
            linewidth=1.2,
            alpha=0.7,
            color="#d4a557",
            label="Predicted (Train)",
        )
    if split_time is not None:
        ax.axvline(split_time, color="#c0392b", linestyle=":", lw=1.6, label="Train / Test Split")
    ax.plot(
        time_test,
        y_true,
        linestyle="-",
        linewidth=1.6,
        alpha=0.9,
        color="#2c3e50",
        label="True",
    )
    ax.plot(
        time_test,
        y_pred,
        linestyle="-",
        linewidth=1.6,
        alpha=0.9,
        color="#c0392b",
        label="Predicted",
    )
    if x_limits is not None:
        ax.set_xlim(x_limits)
    ax.set_xlabel("Time")
    ax.set_ylabel("Solar-Wind Speed (km/s)")
    if x_limits is not None:
        start_label = pd.Timestamp(x_limits[0]).strftime("%Y-%m-%d")
        end_label = pd.Timestamp(x_limits[1]).strftime("%Y-%m-%d")
        subtitle = f"Full Data Range {start_label} - {end_label}"
    else:
        subtitle = "Full Data Range"
    title = (
        f"{experiment_label} True vs Predicted Scatter (Time-Aligned) · {subtitle}"
        if experiment_label
        else f"True vs Predicted Scatter (Time-Aligned) · {subtitle}"
    )
    ax.set_title(title)
    ax.grid(axis="x", linestyle=":", color="#d8dee8", alpha=0.9)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(framealpha=0.9, edgecolor="#dbe1ea", fontsize=8, loc="upper left")
    plt.tight_layout()
    save_path = output_dir / "elasticnet_timeseries.png"
    plt.savefig(save_path)
    plt.close()
    return save_path

def plot_residual_scatter(y_pred: np.ndarray, residual: np.ndarray, output_dir: Path):
    plt.figure(figsize=(7, 5), dpi=300)
    plt.scatter(y_pred, residual, alpha=0.7, s=24, c="#34495e")
    plt.axhline(y=0, color="red", linestyle="--", lw=2)
    plt.xlabel("Predicted Solar-Wind Speed (km/s)")
    plt.ylabel("Residual (True - Predicted)")
    plt.title("Residual Scatter")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_path = output_dir / "elasticnet_residual_scatter.png"
    plt.savefig(save_path, bbox_inches="tight")
    plt.close()
    return save_path

def plot_residual_histogram(residual: np.ndarray, output_dir: Path):
    plt.figure(figsize=(7, 5), dpi=300)
    sns.histplot(residual, bins=20, kde=True, color="#34495e")
    plt.xlabel("Residual (True - Predicted)")
    plt.ylabel("Count")
    plt.title("Residual Histogram")
    plt.tight_layout()
    save_path = output_dir / "elasticnet_residual_hist.png"
    plt.savefig(save_path, bbox_inches="tight")
    plt.close()
    return save_path


# SHAP 解释

def run_shap_analysis(model: ElasticNet, Xtr: pd.DataFrame, Xte: pd.DataFrame, output_dir: Path):
    def split_feature_lag(feature):
        name, _, lag_text = str(feature).rpartition("_t-")
        if lag_text.isdigit():
            return name, int(lag_text)
        return str(feature), None

    explainer = shap.Explainer(model, Xtr)
    shap_values = explainer(Xte)

    plt.figure(figsize=(10, 8), dpi=300)
    shap.summary_plot(shap_values, Xte, show=False)
    plt.tight_layout()
    summary_path = output_dir / "elasticnet_shap_summary.png"
    plt.savefig(summary_path, bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(10, 8), dpi=300)
    shap.summary_plot(shap_values, Xte, plot_type="bar", show=False)
    plt.tight_layout()
    bar_path = output_dir / "elasticnet_shap_bar.png"
    plt.savefig(bar_path, bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(10, 8), dpi=300)
    shap.plots.waterfall(shap_values[0], show=False, max_display=15)
    plt.tight_layout()
    waterfall_path = output_dir / "elasticnet_shap_waterfall_0.png"
    plt.savefig(waterfall_path, bbox_inches="tight")
    plt.close()

    shap_importance = pd.DataFrame({
        "feature": Xte.columns,
        "mean_abs_shap": np.abs(shap_values.values).mean(axis=0)
    }).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
    shap_importance["variable"] = shap_importance["feature"].map(lambda item: split_feature_lag(item)[0])
    shap_importance["lag"] = shap_importance["feature"].map(lambda item: split_feature_lag(item)[1])
    variable_importance = (
        shap_importance
        .groupby("variable", as_index=False)["mean_abs_shap"]
        .mean()
        .sort_values("mean_abs_shap", ascending=False)
        .reset_index(drop=True)
    )
    lag_profile = (
        shap_importance.loc[shap_importance["lag"].notna()]
        .groupby("lag", as_index=False)["mean_abs_shap"]
        .mean()
        .sort_values("lag")
        .reset_index(drop=True)
    )
    shap_importance_path = output_dir / "elasticnet_shap_importance.csv"
    variable_importance_path = output_dir / "elasticnet_shap_variable_importance.csv"
    lag_profile_path = output_dir / "elasticnet_shap_lag_profile.csv"
    shap_importance.to_csv(shap_importance_path, index=False, encoding="utf-8-sig")
    variable_importance.to_csv(variable_importance_path, index=False, encoding="utf-8-sig")
    lag_profile.to_csv(lag_profile_path, index=False, encoding="utf-8-sig")

    return {
        "summary_path": summary_path,
        "bar_path": bar_path,
        "waterfall_path": waterfall_path,
        "importance": shap_importance,
        "importance_path": shap_importance_path,
        "variable_importance": variable_importance,
        "variable_importance_path": variable_importance_path,
        "lag_profile": lag_profile,
        "lag_profile_path": lag_profile_path,
    }


# 主流程

def main(config_path: str):
    cfg = load_llm_json_config(config_path)
    output_dir = Path(config_path).resolve().parent.parent / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    merged = load_and_merge_data(cfg)
    window_result = build_sliding_window(
        merged.X,
        merged.y,
        merged.time,
        cfg.time_window_config,
    )
    X_all, y_all, time_all, feature_names = (
        window_result.X_all,
        window_result.y_all,
        window_result.time_all,
        window_result.feature_names,
    )
    Xtr, Xte, ytr, yte, time_train, time_test, scaler = split_and_scale_dataset(
        X_all,
        y_all,
        time_all,
        cfg.time_window_config.test_split_ratio,
        feature_names
    )

    model = train_elasticnet_model(Xtr, ytr, cfg.elasticnet_config)
    metrics, ytr_pred, yte_pred = evaluate_model(model, Xtr, Xte, ytr, yte)
    coef_df = make_coefficient_table(model, feature_names)
    coef_df.to_csv(output_dir / "elasticnet_coefficients.csv", index=False, encoding="utf-8-sig")
    with open(output_dir / "elasticnet_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    residual = yte - yte_pred
    full_time = np.concatenate([time_train, time_test])
    full_y = np.concatenate([ytr, yte])
    full_y_pred = np.concatenate([ytr_pred, yte_pred])
    x_limits = (full_time.min(), full_time.max()) if len(full_time) > 0 else None
    split_time = time_test[0] if len(time_test) > 0 else None
    figure_paths = {
        "coefficients": plot_feature_coefficients(coef_df, output_dir),
        "scatter": plot_prediction_scatter(
            yte,
            yte_pred,
            metrics,
            output_dir,
            experiment_label="ElasticNet",
            train_true=ytr,
            train_pred=ytr_pred,
        ),
        "timeseries": plot_prediction_series(
            time_test,
            yte,
            yte_pred,
            output_dir,
            experiment_label="ElasticNet",
            time_train=time_train,
            train_true=ytr,
            train_pred=ytr_pred,
            x_limits=x_limits,
            split_time=split_time,
        ),
        "residual_scatter": plot_residual_scatter(yte_pred, residual, output_dir),
        "residual_hist": plot_residual_histogram(residual, output_dir)
    }
    shap_result = run_shap_analysis(model, Xtr, Xte, output_dir)

    print("ElasticNet 训练完成")
    print(f"滑动窗口后样本数: {len(X_all)}")
    print(f"滑动窗口共 {window_result.total_windows} 个")
    print(f"训练集 RMSE: {metrics['train_rmse']:.3f}")
    print(f"测试集 RMSE: {metrics['test_rmse']:.3f}")
    print(f"训练集 R2: {metrics['train_r2']:.3f}")
    print(f"测试集 R2: {metrics['test_r2']:.3f}")
    print(f"测试集 Pearson r: {metrics['test_pearson_r']:.3f}")
    print(f"测试集均值对照组 RMSE: {metrics['baseline_test_rmse']:.3f}")
    print("系数绝对值 Top 特征:")
    print(coef_df.head(10).to_string(index=False))
    print("SHAP 重要性 Top 特征:")
    print(shap_result['importance'].head(10).to_string(index=False))

    return {
        "config": cfg.model_dump(mode="json"),
        "metrics": metrics,
        "coefficients": coef_df,
        "shap_importance": shap_result['importance'],
        "model": model,
        "scaler": scaler,
        "time_train": time_train,
        "time_test": time_test,
        "y_train": ytr,
        "y_test": yte,
        "y_train_pred": ytr_pred,
        "y_test_pred": yte_pred,
        "figure_paths": figure_paths,
        "shap_paths": {
            "summary": shap_result['summary_path'],
            "bar": shap_result['bar_path'],
            "waterfall": shap_result['waterfall_path'],
            "importance_csv": shap_result['importance_path']
        },
        "output_dir": output_dir
    }


#主函数调用
if __name__ == "__main__":
    main(r"D:\astro\ElasticNet\json_Einput\Elasticnet.txt")
