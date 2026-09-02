import json
import warnings
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
    time_column: str
    target_column: str
    feature_columns: List[str]

    def model_post_init(self, __context):
        if not self.omni_file_path.exists():
            raise FileNotFoundError(f"OMNI文件不存在 {self.omni_file_path}")
        if not self.lhaaso_file_path.exists():
            raise FileNotFoundError(f"LHAASO文件不存在 {self.lhaaso_file_path}")

class TimeWindowConfig(BaseModel):
    window_size: int = Field(ge=1, le=196, description="滑动窗口天数，1~196")
    test_split_ratio: float = Field(ge=0.1, le=0.5)
    use_lag_feature: bool
    max_lag_day: int = Field(ge=0, le=10)

class ElasticNetConfig(BaseModel):
    alpha: float
    l1_ratio: float
    random_state: int

class ExperimentConfig(BaseModel):
    file_config: FileConfig
    time_window_config: TimeWindowConfig
    elasticnet_config: ElasticNetConfig

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
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(file_path, sep=r"\s+|,", engine="python")
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

def load_and_merge_data(cfg: ExperimentConfig):
    file_cfg = cfg.file_config
    df_omni = _read_table(file_cfg.omni_file_path)
    df_lhaaso = _read_table(file_cfg.lhaaso_file_path)

    if file_cfg.time_column not in df_omni.columns:
        raise KeyError(f"OMNI数据缺少时间列: {file_cfg.time_column}")
    if file_cfg.time_column not in df_lhaaso.columns:
        raise KeyError(f"LHAASO数据缺少时间列: {file_cfg.time_column}")

    df_omni[file_cfg.time_column] = _normalize_time_column(df_omni[file_cfg.time_column])
    df_lhaaso[file_cfg.time_column] = _normalize_time_column(df_lhaaso[file_cfg.time_column])
    df_merge = pd.merge(df_omni, df_lhaaso, on=file_cfg.time_column, how="inner")

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
    print(f"数据合并完成，有效样本数: {len(df_merge)}")
    return X, y, time_raw


# 时间窗构造与数据集切分

def build_sliding_window(X_raw: pd.DataFrame, y_raw: pd.Series, time_raw: pd.Series, tw_cfg: TimeWindowConfig):
    window_size = tw_cfg.window_size
    if len(X_raw) <= window_size:
        raise ValueError(f"有效样本数 {len(X_raw)} 小于窗口大小 {window_size}")

    arr_x = X_raw.to_numpy(dtype=float)
    arr_y = y_raw.to_numpy(dtype=float)
    arr_t = pd.to_datetime(time_raw).to_numpy()

    X_all, y_all, time_all = [], [], []
    feature_names = []
    for lag in range(window_size, 0, -1):
        for col in X_raw.columns:
            feature_names.append(f"{col}_t-{lag}")

    for i in range(window_size, len(arr_x)):
        X_all.append(arr_x[i - window_size:i, :].reshape(-1))
        y_all.append(arr_y[i])
        time_all.append(arr_t[i])

    return np.asarray(X_all), np.asarray(y_all), np.asarray(time_all), feature_names

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

def plot_prediction_scatter(y_true: np.ndarray, y_pred: np.ndarray, metrics: dict, output_dir: Path):
    min_val = min(np.min(y_true), np.min(y_pred))
    max_val = max(np.max(y_true), np.max(y_pred))
    plt.figure(figsize=(7, 6), dpi=300)
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
    plt.title("True vs Predicted Scatter")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_path = output_dir / "elasticnet_scatter.png"
    plt.savefig(save_path, bbox_inches="tight")
    plt.close()
    return save_path

def plot_prediction_series(time_test: np.ndarray, y_true: np.ndarray, y_pred: np.ndarray, output_dir: Path):
    plt.figure(figsize=(20, 5), dpi=300)
    plt.plot(time_test, y_true, label="True", lw=1.8, color="#2c3e50")
    plt.plot(time_test, y_pred, label="Predicted", lw=1.8, color="#c0392b")
    plt.xlabel("Time")
    plt.ylabel("Solar-Wind Speed (km/s)")
    plt.title("Test Set Time-Series Comparison")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_path = output_dir / "elasticnet_timeseries.png"
    plt.savefig(save_path, bbox_inches="tight")
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
    shap_importance_path = output_dir / "elasticnet_shap_importance.csv"
    shap_importance.to_csv(shap_importance_path, index=False, encoding="utf-8-sig")

    return {
        "summary_path": summary_path,
        "bar_path": bar_path,
        "waterfall_path": waterfall_path,
        "importance": shap_importance,
        "importance_path": shap_importance_path
    }


# 主流程

def main(config_path: str):
    cfg = load_llm_json_config(config_path)
    output_dir = Path(config_path).resolve().parent.parent / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    X_raw, y_raw, time_raw = load_and_merge_data(cfg)
    X_all, y_all, time_all, feature_names = build_sliding_window(X_raw, y_raw, time_raw, cfg.time_window_config)
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
    figure_paths = {
        "coefficients": plot_feature_coefficients(coef_df, output_dir),
        "scatter": plot_prediction_scatter(yte, yte_pred, metrics, output_dir),
        "timeseries": plot_prediction_series(time_test, yte, yte_pred, output_dir),
        "residual_scatter": plot_residual_scatter(yte_pred, residual, output_dir),
        "residual_hist": plot_residual_histogram(residual, output_dir)
    }
    shap_result = run_shap_analysis(model, Xtr, Xte, output_dir)

    print("ElasticNet 训练完成")
    print(f"滑动窗口后样本数: {len(X_all)}")
    print(f"训练集 RMSE: {metrics['train_rmse']:.3f}")
    print(f"测试集 RMSE: {metrics['test_rmse']:.3f}")
    print(f"训练集 R2: {metrics['train_r2']:.3f}")
    print(f"测试集 R2: {metrics['test_r2']:.3f}")
    print(f"测试集 Pearson r: {metrics['test_pearson_r']:.3f}")
    print(f"测试集均值基线 RMSE: {metrics['baseline_test_rmse']:.3f}")
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