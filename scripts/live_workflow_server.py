from __future__ import annotations

import io
import json
import mimetypes
import re
import shutil
import sys
import threading
import traceback
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
from pydantic import BaseModel, Field

from core.decision_unified import DecisionLayerService
from core.llm_gateway import LLMGateway
from core.runtime_config import get_llm_role_models, load_project_env
from core.state_repository import UnifiedStateRepository
from core.unified_schema import (
    DataDictionary,
    EvaluationSpec,
    FieldDescriptor,
    ResearchQuestion,
    ScientificConstraints,
    ScientificTask,
    ScientificTaskPayload,
    VariableBinding,
)
from scripts.run_real_api_two_round_demo import build_real_llm_control

HOST = "127.0.0.1"
PORT = 8765
LIVE_ROOT = REPO_ROOT / "runtime" / "live_session" / "current"
STATE_DIR = LIVE_ROOT / "state"
STATUS_PATH = LIVE_ROOT / "session_status.json"
UPLOAD_MANIFEST_PATH = STATE_DIR / "upload_manifest.json"
MODEL_USAGE_PATH = STATE_DIR / "model_usage.json"


class StaleSessionError(RuntimeError):
    """Raised when a background worker belongs to an outdated session generation."""

TEXT_FILE_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json"}
TABULAR_FILE_SUFFIXES = {".csv", ".xlsx", ".xls"}
TIME_COLUMN_CANDIDATES = {"time", "timestamp", "datetime", "date"}
TARGET_COLUMN_CANDIDATES = {"vsw", "solarwindspeed", "solar_wind_speed", "target"}
PRIMARY_SIGNAL_CANDIDATES = {"deltadec", "delta_dec", "delta"}


class QuestionVariableAnalysis(BaseModel):
    x_variable: str | None = None
    y_variable: str | None = None
    m_candidates: list[str] = Field(default_factory=list)
    question_type: str = "scientific_inquiry"
    needs_confirmation: bool = False
    clarification_question: str | None = None
    rationale: str | None = None


class DataDictionaryFieldConfig(BaseModel):
    field_name: str
    file_name: str | None = None
    category: str | None = None
    physical_meaning: str | None = None


class DataDictionaryConfigPayload(BaseModel):
    time_column: str | None = None
    fields: list[DataDictionaryFieldConfig] = Field(default_factory=list)


def normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "").replace("_", "")


def sanitize_filename(name: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in Path(name).name)


def parse_multipart_form(content_type: str, body: bytes) -> tuple[dict[str, list[str]], dict[str, list[dict[str, Any]]]]:
    match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not match:
        raise ValueError("multipart 请求缺少 boundary。")

    boundary = match.group("boundary").strip().strip('"').encode("utf-8")
    delimiter = b"--" + boundary
    fields: dict[str, list[str]] = {}
    files: dict[str, list[dict[str, Any]]] = {}

    for part in body.split(delimiter):
        chunk = part.strip()
        if not chunk or chunk == b"--":
            continue
        if chunk.endswith(b"--"):
            chunk = chunk[:-2].rstrip()

        header_blob, separator, content = chunk.partition(b"\r\n\r\n")
        if not separator:
            continue

        headers: dict[str, str] = {}
        for line in header_blob.decode("utf-8", errors="ignore").split("\r\n"):
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

        disposition = headers.get("content-disposition", "")
        name_match = re.search(r'name="([^"]+)"', disposition)
        if not name_match:
            continue
        field_name = name_match.group(1)
        payload = content[:-2] if content.endswith(b"\r\n") else content
        file_match = re.search(r'filename="([^"]*)"', disposition)
        if file_match and file_match.group(1):
            files.setdefault(field_name, []).append(
                {
                    "name": file_match.group(1),
                    "content": payload,
                }
            )
        else:
            fields.setdefault(field_name, []).append(payload.decode("utf-8", errors="ignore"))

    return fields, files


def ensure_relative_to(base: Path, candidate: Path) -> Path:
    resolved_base = base.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_base)
    except ValueError as exc:
        raise PermissionError("非法路径访问。") from exc
    return resolved_candidate


def read_table(file_path: Path) -> pd.DataFrame:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(file_path)
    raise ValueError(f"暂不支持的数据文件类型: {suffix}")


def read_table_from_upload(file_name: str, content: bytes) -> pd.DataFrame:
    suffix = Path(file_name).suffix.lower()
    buffer = io.BytesIO(content)
    if suffix == ".csv":
        return pd.read_csv(buffer)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(buffer)
    raise ValueError(f"暂不支持的数据文件类型: {suffix}")


def is_numeric_series(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return True
    converted = pd.to_numeric(series, errors="coerce")
    return bool(converted.notna().mean() >= 0.8)


def detect_time_column(columns: list[str]) -> str:
    normalized = {normalize_key(column): column for column in columns}
    for candidate in TIME_COLUMN_CANDIDATES:
        if candidate in normalized:
            return normalized[candidate]
    return columns[0]


def detect_target_column(columns: list[str], numeric_columns: list[str]) -> str:
    normalized = {normalize_key(column): column for column in columns}
    for candidate in TARGET_COLUMN_CANDIDATES:
        if candidate in normalized:
            return normalized[candidate]
    if numeric_columns:
        return numeric_columns[-1]
    raise ValueError("未检测到可用的目标变量列。")


def detect_primary_signal(columns: list[str], numeric_columns: list[str], target_column: str) -> str:
    normalized = {normalize_key(column): column for column in columns}
    for candidate in PRIMARY_SIGNAL_CANDIDATES:
        if candidate in normalized and normalized[candidate] != target_column:
            return normalized[candidate]
    for column in numeric_columns:
        if column != target_column:
            return column
    return target_column


def heuristic_question_analysis(question: str) -> QuestionVariableAnalysis:
    normalized = question.replace("（", "(").replace("）", ")")
    variable_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+\-]*|[\u4e00-\u9fff]{2,12}", normalized)
    unique_tokens: list[str] = []
    for token in variable_tokens:
        if token not in unique_tokens:
            unique_tokens.append(token)

    x_variable = None
    y_variable = None
    m_candidates: list[str] = []
    if "日影南北偏移" in question:
        x_variable = "日影南北偏移"
    elif "DeltaDec" in question or "ΔDec" in question:
        x_variable = "DeltaDec"

    if "Vsw" in question:
        y_variable = "Vsw"
    elif "太阳风速度" in question:
        y_variable = "太阳风速度"

    candidate_blocks = re.findall(r"(通过|经由|via|中介|控制)([^，。；;]+)", normalized, flags=re.IGNORECASE)
    for _, block in candidate_blocks:
        for token in re.split(r"[、,，/ ]+", block):
            cleaned = token.strip()
            if cleaned and cleaned not in {x_variable, y_variable} and cleaned not in m_candidates:
                m_candidates.append(cleaned)

    question_type = "forecasting" if any(token in question.lower() for token in ("预测", "forecast", "prediction")) else "scientific_inquiry"
    needs_confirmation = not x_variable or not y_variable
    clarification_question = (
        "我还没有稳定识别出这次科学问题中的核心解释变量和目标变量，请补充确认。"
        if needs_confirmation
        else None
    )
    rationale = "已根据问题文本中的变量实体和语义线索生成初步绑定。"
    return QuestionVariableAnalysis(
        x_variable=x_variable,
        y_variable=y_variable,
        m_candidates=m_candidates[:6],
        question_type=question_type,
        needs_confirmation=needs_confirmation,
        clarification_question=clarification_question,
        rationale=rationale,
    )


def analyze_question_with_llm(question: str, model: str) -> QuestionVariableAnalysis:
    gateway = LLMGateway(model=model, allow_fallback=False)
    return gateway.invoke(
        [
            {
                "role": "system",
                "content": (
                    "你是科研任务结构化助手。请从科学问题中识别：核心解释变量 x_variable、目标变量 y_variable、"
                    "候选中介变量 m_candidates、问题类型 question_type。变量名称必须尽量沿用用户原文。"
                    "如果无法稳定识别 x 或 y，则 needs_confirmation=true，并给出 clarification_question。"
                    "question_type 只能是 forecasting 或 scientific_inquiry。"
                ),
            },
            {
                "role": "user",
                "content": f"科学问题：{question}",
            },
        ],
        response_model=QuestionVariableAnalysis,
    )


def analyze_question(question: str, model: str) -> QuestionVariableAnalysis:
    heuristic = heuristic_question_analysis(question)
    try:
        llm_result = analyze_question_with_llm(question, model)
        return QuestionVariableAnalysis(
            x_variable=llm_result.x_variable or heuristic.x_variable,
            y_variable=llm_result.y_variable or heuristic.y_variable,
            m_candidates=(llm_result.m_candidates or heuristic.m_candidates)[:6],
            question_type=llm_result.question_type or heuristic.question_type,
            needs_confirmation=llm_result.needs_confirmation or not (llm_result.x_variable or heuristic.x_variable) or not (llm_result.y_variable or heuristic.y_variable),
            clarification_question=llm_result.clarification_question or heuristic.clarification_question,
            rationale=llm_result.rationale or heuristic.rationale,
        )
    except Exception:
        return heuristic


def build_variable_override_payload(
    *,
    x_variable: str | None = None,
    y_variable: str | None = None,
    m_candidates: list[str] | None = None,
    question_type: str | None = None,
) -> dict[str, Any]:
    return {
        "x_variable": (x_variable or "").strip() or None,
        "y_variable": (y_variable or "").strip() or None,
        "m_candidates": [item.strip() for item in (m_candidates or []) if item.strip()],
        "question_type": (question_type or "").strip() or None,
    }


def parse_m_candidates_payload(raw_candidates: str) -> list[str]:
    raw_candidates = raw_candidates.strip()
    if not raw_candidates:
        return []
    try:
        payload = json.loads(raw_candidates)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    return [item.strip() for item in re.split(r"[，、]", raw_candidates) if item.strip()]


def derive_overrides_from_task(task: ScientificTask) -> dict[str, Any]:
    variables = task.payload.research_question.variables
    return build_variable_override_payload(
        x_variable=variables.x,
        y_variable=variables.y or task.payload.research_question.target,
        m_candidates=list(variables.m_candidates or []),
        question_type=task.payload.research_question.question_type,
    )


def parse_data_dictionary_config(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("data_dictionary_config 必须是 JSON 对象。")
    return DataDictionaryConfigPayload.model_validate(payload).model_dump(mode="json", exclude_none=True)


def inspect_uploaded_data_files(files: list[dict[str, Any]]) -> dict[str, Any]:
    if not files:
        raise ValueError("至少需要上传一个实验数据文件。")

    tables: list[dict[str, Any]] = []
    target_suggestion: str | None = None
    x_suggestion: str | None = None
    mediator_suggestions: list[str] = []
    time_column: str | None = None

    for item in files:
        file_name = sanitize_filename(str(item["name"]))
        table = read_table_from_upload(file_name, item["content"])
        columns = [str(column) for column in table.columns.tolist()]
        numeric_columns = [column for column in columns if is_numeric_series(table[column])]
        detected_time = detect_time_column(columns)
        detected_target = detect_target_column(columns, numeric_columns) if numeric_columns else None
        detected_primary = detect_primary_signal(columns, numeric_columns, detected_target) if detected_target else None
        time_column = time_column or detected_time
        target_suggestion = target_suggestion or detected_target
        x_suggestion = x_suggestion or detected_primary
        for column in numeric_columns:
            if column not in {detected_target, detected_primary} and column not in mediator_suggestions:
                mediator_suggestions.append(column)

        tables.append(
            {
                "file_name": file_name,
                "row_count": int(len(table)),
                "columns": [
                    {
                        "field_name": column,
                        "data_type": str(table[column].dtype),
                        "is_numeric": bool(is_numeric_series(table[column])),
                        "missing_rate": float(table[column].isna().mean() if len(table[column]) else 0.0),
                        "suggested_category": (
                            "time"
                            if column == detected_time
                            else "target"
                            if column == detected_target
                            else "core_explanatory"
                            if column == detected_primary
                            else "candidate_mediator"
                            if column in numeric_columns
                            else "deprecated"
                        ),
                        "physical_meaning": "",
                    }
                    for column in columns
                ],
            }
        )

    return {
        "tables": tables,
        "suggested": {
            "time_column": time_column,
            "target_variable": target_suggestion,
            "core_explanatory": x_suggestion,
            "candidate_mediators": mediator_suggestions[:8],
        },
    }


def validate_data_dictionary_bindings(
    *,
    tables: list[tuple[Path, pd.DataFrame]],
    config_entries: list[dict[str, Any]],
) -> None:
    source_columns_map = {
        path.name: {str(column) for column in table.columns.tolist()}
        for path, table in tables
    }
    all_columns = {column for columns in source_columns_map.values() for column in columns}
    physical_meaning_owners: dict[str, str] = {}

    for item in config_entries:
        field_name = str(item.get("field_name") or "").strip()
        file_name = str(item.get("file_name") or "").strip()
        category = str(item.get("category") or "").strip()
        physical_meaning = str(item.get("physical_meaning") or "").strip()
        if not field_name:
            raise ValueError("数据字典配置中存在空字段名。")

        if file_name:
            if file_name not in source_columns_map:
                raise ValueError(f"数据字典配置引用了不存在的数据文件: {file_name}")
            if field_name not in source_columns_map[file_name]:
                raise ValueError(f"数据字典配置中的字段 {field_name} 不存在于文件 {file_name}。")
        elif field_name not in all_columns:
            raise ValueError(f"数据字典配置中的字段 {field_name} 不存在于任何已上传数据文件。")

        if category != "deprecated" and not physical_meaning:
            raise ValueError(f"字段 {field_name} 已参与建模配置，必须填写物理量释义。")

        if category != "deprecated" and physical_meaning:
            owner = physical_meaning_owners.get(physical_meaning)
            current_owner = f"{file_name or 'ANY'}::{field_name}"
            if owner and owner != current_owner:
                raise ValueError(f"物理量释义 {physical_meaning} 同时绑定到多个字段，请保持一一对应。")
            physical_meaning_owners[physical_meaning] = current_owner


def build_dictionary_and_task(
    *,
    question: str,
    raw_data_paths: list[Path],
    variable_overrides: dict[str, Any] | None = None,
    data_dictionary_config: dict[str, Any] | None = None,
) -> tuple[ScientificTask, DataDictionary]:
    if not raw_data_paths:
        raise ValueError("至少需要上传一个数据文件。")

    tables = [(path, read_table(path)) for path in raw_data_paths]
    first_path, first_table = tables[0]
    all_columns: list[str] = []
    numeric_columns: list[str] = []
    source_columns_map: dict[str, list[str]] = {}
    field_sources: dict[str, list[str]] = {}
    for path, table in tables:
        source_columns = [str(column) for column in table.columns.tolist()]
        source_columns_map[path.name] = source_columns
        for column in source_columns:
            if column not in all_columns:
                all_columns.append(column)
            field_sources.setdefault(column, [])
            if path.name not in field_sources[column]:
                field_sources[column].append(path.name)
            if is_numeric_series(table[column]) and column not in numeric_columns:
                numeric_columns.append(column)
    if not numeric_columns:
        raise ValueError("数据文件中没有检测到可用于建模的数值列。")

    config_field_entries = [
        item
        for item in (data_dictionary_config or {}).get("fields", [])
        if isinstance(item, dict) and isinstance(item.get("field_name"), str)
    ]
    validate_data_dictionary_bindings(tables=tables, config_entries=config_field_entries)
    aggregated_config_fields: dict[str, dict[str, Any]] = {}
    for item in config_field_entries:
        field_name = item["field_name"]
        current = aggregated_config_fields.get(field_name)
        if not current:
            aggregated_config_fields[field_name] = dict(item)
            continue
        if str(item.get("physical_meaning") or "").strip() and not str(current.get("physical_meaning") or "").strip():
            current["physical_meaning"] = item["physical_meaning"]
        current_category = str(current.get("category") or "").strip()
        next_category = str(item.get("category") or "").strip()
        if next_category and current_category in {"", "deprecated"}:
            current["category"] = next_category

    deprecated_fields = {
        field_name
        for field_name, item in aggregated_config_fields.items()
        if str(item.get("category") or "").strip() in {"deprecated", "discarded"}
    }
    configured_time = (data_dictionary_config or {}).get("time_column")
    time_column = configured_time if isinstance(configured_time, str) and configured_time in all_columns else detect_time_column(all_columns)
    usable_numeric_columns = [column for column in numeric_columns if column not in deprecated_fields]

    configured_target_candidates = [
        field_name
        for field_name, item in aggregated_config_fields.items()
        if str(item.get("category") or "").strip() == "target" and field_name in usable_numeric_columns
    ]
    target_column = (
        (variable_overrides or {}).get("y_variable")
        if isinstance((variable_overrides or {}).get("y_variable"), str)
        and (variable_overrides or {}).get("y_variable") in usable_numeric_columns
        else (configured_target_candidates[0] if configured_target_candidates else detect_target_column(all_columns, usable_numeric_columns))
    )

    configured_core_candidates = [
        field_name
        for field_name, item in aggregated_config_fields.items()
        if str(item.get("category") or "").strip() == "core_explanatory" and field_name in usable_numeric_columns
    ]
    configured_mediator_candidates = [
        field_name
        for field_name, item in aggregated_config_fields.items()
        if str(item.get("category") or "").strip() == "candidate_mediator" and field_name in usable_numeric_columns
    ]
    primary_signal = (
        (variable_overrides or {}).get("x_variable")
        if isinstance((variable_overrides or {}).get("x_variable"), str)
        and (variable_overrides or {}).get("x_variable") in usable_numeric_columns
        else configured_core_candidates[0]
        if configured_core_candidates
        else detect_primary_signal(all_columns, usable_numeric_columns, target_column)
    )
    selected_feature_candidates = [
        column
        for column in [primary_signal, *configured_core_candidates, *configured_mediator_candidates]
        if column in usable_numeric_columns and column != target_column
    ]
    feature_candidates = (
        list(dict.fromkeys(selected_feature_candidates))
        if selected_feature_candidates
        else [column for column in usable_numeric_columns if column not in {target_column}]
    )
    override_payload = build_variable_override_payload(**(variable_overrides or {}))
    conceptual_x = override_payload["x_variable"] or primary_signal
    conceptual_y = override_payload["y_variable"] or target_column

    field_descriptors: list[FieldDescriptor] = []
    seen_fields: set[str] = set()
    for path, table in tables:
        for column in table.columns:
            field_name = str(column)
            if field_name in seen_fields:
                continue
            seen_fields.add(field_name)
            series = table[column]
            data_type = str(series.dtype)
            field_config = aggregated_config_fields.get(field_name, {})
            field_descriptors.append(
                FieldDescriptor(
                    field_name=field_name,
                    data_type=data_type,
                    physical_meaning=(
                        str(field_config.get("physical_meaning") or "").strip()
                        or ("弃用字段" if str(field_config.get("category") or "").strip() == "deprecated" else "")
                        or ("target" if field_name == target_column else ("time" if field_name == time_column else "feature"))
                    ),
                    missing_rate=float(series.isna().mean() if len(series) else 0.0),
                    is_target=field_name == target_column,
                    user_notes=(
                        f"sources={','.join(field_sources.get(field_name, []))}; "
                        f"category={str(field_config.get('category') or 'auto')}"
                    ),
                )
            )

    source_details = {}
    signal_source_path = first_path
    for path, table in tables:
        source_columns = source_columns_map[path.name]
        source_time = detect_time_column(source_columns)
        if conceptual_x in source_columns or primary_signal in source_columns:
            signal_source_path = path
        source_details[path.stem] = {
            "path": f"data/raw/{path.name}",
            "time_column": source_time,
            "target_column": target_column if target_column in source_columns else None,
        }
    data_sources = {
        "omni": source_details.get(first_path.stem),
        "lhaaso": source_details.get(signal_source_path.stem, source_details.get(first_path.stem)),
    }
    for source_id, details in source_details.items():
        if source_id not in data_sources:
            data_sources[source_id] = details

    time_source = next((table for _, table in tables if time_column and time_column in table.columns), first_table)
    time_series = time_source[time_column].astype(str) if time_column and time_column in time_source.columns else None
    mediator_candidates = override_payload["m_candidates"] or configured_mediator_candidates or [
        column for column in feature_candidates if column not in {target_column, primary_signal}
    ][:6]
    question_type = override_payload["question_type"] or (
        "forecasting" if any(token in question for token in ("预测", "forecast", "prediction")) else "scientific_inquiry"
    )
    dictionary = DataDictionary(
        dictionary_id=f"DICT_LIVE_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        generated_at=datetime.now(),
        version="1.0",
        dataset_name=" + ".join(path.stem for path, _ in tables[:3]),
        total_samples=int(sum(len(table) for _, table in tables)),
        time_column=time_column,
        time_format="auto",
        time_range={"start": time_series.iloc[0], "end": time_series.iloc[-1]} if time_series is not None and len(time_series) else None,
        fields=field_descriptors,
        target_candidates=[target_column],
        feature_candidates=feature_candidates,
        user_supplementary={
            field_name: str(item.get("physical_meaning") or "").strip()
            for field_name, item in aggregated_config_fields.items()
            if str(item.get("physical_meaning") or "").strip()
        },
    )
    task = ScientificTask(
        task_id=f"ST_LIVE_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        payload=ScientificTaskPayload(
            research_question=ResearchQuestion(
                text=question,
                target=conceptual_y,
                question_type=question_type,
                variables=VariableBinding(
                    x=conceptual_x,
                    y=conceptual_y,
                    m_candidates=mediator_candidates[:6],
                ),
                keywords=[conceptual_x, conceptual_y, *mediator_candidates[:4]],
                clarified=bool(override_payload["x_variable"] and override_payload["y_variable"]),
            ),
            evaluation=EvaluationSpec(
                primary_metric="Pearson_r",
                secondary_metrics=["RMSE", "MAE"],
                visual_analysis=["prediction_vs_truth", "scatter_plot"],
            ),
            constraints=ScientificConstraints(
                no_future_information=True,
                validation_feedback_allowed=True,
                final_test_blind=True,
                max_hypotheses_per_level=5,
                min_active_hypotheses=4,
                max_rounds=10,
                max_experiments_per_round=3,
                notes=["前端真实输入启动"],
            ),
            data_sources=data_sources,
        ),
    )
    return task, dictionary


def ingest_knowledge_files(knowledge_dir: Path, text_dir: Path, files: list[dict[str, Any]]) -> None:
    manifest: list[dict[str, Any]] = []
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    for item in files:
        file_name = sanitize_filename(str(item["name"]))
        raw_path = knowledge_dir / file_name
        raw_path.write_bytes(item["content"])
        suffix = raw_path.suffix.lower()
        text_path = text_dir / f"{raw_path.stem}.txt"
        extraction_status = "placeholder_only"
        if suffix in TEXT_FILE_SUFFIXES:
            text_path.write_text(item["content"].decode("utf-8", errors="ignore"), encoding="utf-8")
            extraction_status = "ready"
        else:
            text_path.write_text(
                f"uploaded knowledge file: {raw_path.name}\npath: uploads/knowledge/{raw_path.name}",
                encoding="utf-8",
            )
        manifest.append(
            {
                "file_name": raw_path.name,
                "file_type": suffix or "unknown",
                "size_bytes": len(item["content"]),
                "uploaded_at": datetime.now().isoformat(),
                "storage_path": f"uploads/knowledge/{raw_path.name}",
                "extracted_text_path": f"outputs/pdf_texts/{text_path.name}",
                "extraction_status": extraction_status,
                "knowledge_sync_status": "local_session_only",
                "knowledge_sync_note": "当前仅支持读取百炼知识库，不支持把上传文件写回到百炼托管知识库。",
            }
        )
    return manifest


def write_upload_manifest(records: list[dict[str, Any]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_MANIFEST_PATH.write_text(
        json.dumps({"records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_model_usage_manifest(session_model: str) -> None:
    role_models = get_llm_role_models()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_USAGE_PATH.write_text(
        json.dumps(
            {
                "session_model": session_model,
                "routes": [
                    {
                        "route": "/api/session/analyze-question",
                        "model": session_model,
                        "purpose": "科学问题变量提取与问题类型判断",
                    },
                    {
                        "route": "/api/workflow/start",
                        "model": session_model,
                        "purpose": "会话启动、变量绑定与初始工作区构建",
                    },
                ],
                "roles": [
                    {
                        "role": role,
                        "model": model,
                    }
                    for role, model in role_models.items()
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def persist_data_files(raw_dir: Path, files: list[dict[str, Any]]) -> list[Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    for item in files:
        file_name = sanitize_filename(str(item["name"]))
        target_path = raw_dir / file_name
        target_path.write_bytes(item["content"])
        if target_path.suffix.lower() not in TABULAR_FILE_SUFFIXES:
            raise ValueError(f"暂不支持的数据文件类型: {target_path.suffix}")
        saved_paths.append(target_path)
    return saved_paths


def initialize_live_workspace(
    *,
    question: str,
    knowledge_files: list[dict[str, Any]],
    data_files: list[dict[str, Any]],
    model: str,
    variable_overrides: dict[str, Any] | None = None,
    data_dictionary_config: dict[str, Any] | None = None,
) -> tuple[Path, UnifiedStateRepository, ScientificTask, DataDictionary]:
    if LIVE_ROOT.exists():
        shutil.rmtree(LIVE_ROOT)
    LIVE_ROOT.mkdir(parents=True, exist_ok=True)

    raw_data_paths = persist_data_files(LIVE_ROOT / "data" / "raw", data_files)
    upload_manifest = ingest_knowledge_files(
        LIVE_ROOT / "uploads" / "knowledge",
        LIVE_ROOT / "outputs" / "pdf_texts",
        knowledge_files,
    )

    repo = UnifiedStateRepository(LIVE_ROOT)
    task, dictionary = build_dictionary_and_task(
        question=question,
        raw_data_paths=raw_data_paths,
        variable_overrides=variable_overrides,
        data_dictionary_config=data_dictionary_config,
    )
    repo.initialize_state_skeleton(task, data_dictionary=dictionary, overwrite=True)
    DecisionLayerService(repo).build_candidate_plan(task=task, data_dictionary=dictionary)
    write_upload_manifest(upload_manifest)
    write_model_usage_manifest(model)
    return LIVE_ROOT, repo, task, dictionary


class LiveSessionManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._generation = 0
        self._status: dict[str, Any] = {
            "status": "idle",
            "stage": "waiting_input",
            "message": "等待输入科学问题与数据文件。",
            "question": "",
            "model": "qwen-plus",
            "maxRounds": 2,
            "runRoot": str(LIVE_ROOT),
            "currentRound": 0,
            "updatedAt": datetime.now().isoformat(),
        }
        if STATUS_PATH.exists():
            try:
                persisted = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
                if isinstance(persisted, dict):
                    self._status.update(persisted)
            except Exception:
                pass
        self._synchronize_from_runtime_artifacts()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._synchronize_from_runtime_artifacts()
            return dict(self._status)

    def _write_status(self) -> None:
        LIVE_ROOT.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(self._status, ensure_ascii=False, indent=2), encoding="utf-8")

    def _current_generation(self) -> int:
        with self._lock:
            return self._generation

    def _is_generation_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _abort_if_stale(self, generation: int) -> None:
        if not self._is_generation_current(generation):
            raise StaleSessionError("session generation is stale")

    def _cleanup_if_stale(self, generation: int) -> None:
        if self._is_generation_current(generation):
            return
        shutil.rmtree(LIVE_ROOT, ignore_errors=True)

    def _update(self, *, _generation: int | None = None, **changes: Any) -> None:
        with self._lock:
            if _generation is not None and _generation != self._generation:
                return
            self._status.update(changes)
            self._status["updatedAt"] = datetime.now().isoformat()
            self._write_status()

    def _synchronize_from_runtime_artifacts(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        try:
            repo = UnifiedStateRepository(LIVE_ROOT)
            process_state = repo.load_process_state()
            task = repo.load_task()
            candidate_set = repo.load_candidate_experiments()
            decision_log = repo.load_decision_log()
        except Exception:
            return

        latest_decision = decision_log.decisions[-1] if decision_log.decisions else None
        current_round = max(process_state.current_round, candidate_set.round or 0, int(self._status.get("currentRound") or 0))
        question = task.payload.research_question.text
        model = str(self._status.get("model") or "qwen-plus")
        max_rounds = int(self._status.get("maxRounds") or 2)

        status_updates: dict[str, Any] = {
            "question": question,
            "model": model,
            "maxRounds": max_rounds,
            "runRoot": str(LIVE_ROOT),
            "currentRound": current_round,
        }

        if process_state.current_stage == "awaiting_round_decision":
            status_updates.update(
                status="awaiting_round_decision",
                stage="round_review_requested",
                message="本轮实验已完成，请输入整轮反馈并决定是否继续。",
                planning_status="round_review_requested",
            )
        elif (
            process_state.current_stage == "awaiting_human_approval"
            or (
                latest_decision is not None
                and latest_decision.decision_type == "experiment_selection_requested"
                and (candidate_set.round or 0) >= 1
            )
        ):
            status_updates.update(
                status="awaiting_approval",
                stage="approval_pending",
                message=f"第 {max(candidate_set.round or 0, current_round)} 轮候选实验已生成，等待审批。",
                currentRound=max(candidate_set.round or 0, current_round),
                planning_status="candidate_plan_rebuilt",
            )
        elif process_state.current_stage in {"workflow_terminated", "completed"}:
            status_updates.update(
                status="completed",
                stage="completed",
                message="当前闭环已完成。",
                planning_status="completed",
            )
        elif process_state.current_stage == "failed":
            status_updates.update(
                status="failed",
                stage="failed",
                message=str(self._status.get("message") or "流程执行失败。"),
            )
        elif process_state.current_phase == "next_round":
            status_updates.update(
                status="running",
                stage="next_round_planning",
                message="正在根据本轮反馈生成下一轮候选实验。",
                planning_status="candidate_plan_rebuilding",
            )
        elif process_state.current_phase == "experiment_execution":
            status_updates.update(
                status="running",
                stage="experiment_execution",
                message="正在执行已批准的候选实验。",
                planning_status="experiment_running",
            )
        self._status.update(status_updates)

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._generation += 1
            self._worker = None
            self._status = {
                "status": "idle",
                "stage": "waiting_input",
                "planning_status": "awaiting_data_dictionary",
                "message": "等待输入科学问题与数据文件。",
                "question": "",
                "model": "qwen-plus",
                "maxRounds": 2,
                "runRoot": str(LIVE_ROOT),
                "currentRound": 0,
                "updatedAt": datetime.now().isoformat(),
            }
        shutil.rmtree(LIVE_ROOT, ignore_errors=True)
        self._write_status()
        return dict(self._status)

    def _assert_not_busy(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            raise RuntimeError("当前已有动作正在运行，请等待当前阶段完成。")

    def _start_worker(self, target, **kwargs: Any) -> dict[str, Any]:
        generation = self._current_generation()
        self._worker = threading.Thread(
            target=self._run_worker,
            kwargs={"target": target, "_generation": generation, **kwargs},
            daemon=True,
        )
        self._worker.start()
        return self.snapshot()

    def _run_worker(self, *, target, _generation: int, **kwargs: Any) -> None:
        try:
            target(_generation=_generation, **kwargs)
        finally:
            self._cleanup_if_stale(_generation)

    def _current_model(self) -> str:
        return str(self._status.get("model") or "qwen-plus")

    def _current_round(self) -> int:
        repo = UnifiedStateRepository(LIVE_ROOT)
        process_state = repo.load_process_state()
        candidate_set = repo.load_candidate_experiments()
        return max(process_state.current_round, candidate_set.round or 0, 1)

    def _rebuild_dictionary(self, repo: UnifiedStateRepository) -> DataDictionary:
        try:
            return repo.load_data_dictionary()
        except Exception:
            pass
        raw_paths = sorted((LIVE_ROOT / "data" / "raw").glob("*"))
        if not raw_paths:
            raise RuntimeError("当前会话缺少原始数据文件，无法重建 DataDictionary。")
        task = repo.load_task()
        _, dictionary = build_dictionary_and_task(
            question=task.payload.research_question.text,
            raw_data_paths=raw_paths,
            variable_overrides=derive_overrides_from_task(task),
        )
        return dictionary

    def _build_control(self, repo: UnifiedStateRepository):
        gateway_bundle = build_real_llm_control(repo, LIVE_ROOT, model=self._current_model())
        return gateway_bundle["control"]

    def start(
        self,
        *,
        question: str,
        knowledge_files: list[dict[str, Any]],
        data_files: list[dict[str, Any]],
        model: str,
        rounds: int,
        variable_overrides: dict[str, Any] | None = None,
        data_dictionary_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not question.strip():
            raise ValueError("科学问题不能为空。")
        if not data_files:
            raise ValueError("至少需要上传一个数据文件。")
        self._assert_not_busy()

        self.reset()
        generation = self._current_generation()
        self._update(
            _generation=generation,
            status="starting",
            stage="workspace_preparing",
            message="正在初始化真实工作区。",
            question=question.strip(),
            model=model,
            maxRounds=max(1, rounds),
        )
        return self._start_worker(
            self._prepare_initial_review,
            question=question.strip(),
            knowledge_files=knowledge_files,
            data_files=data_files,
            model=model,
            rounds=max(1, rounds),
            variable_overrides=variable_overrides or {},
            data_dictionary_config=data_dictionary_config,
        )

    def _prepare_initial_review(
        self,
        *,
        _generation: int,
        question: str,
        knowledge_files: list[dict[str, Any]],
        data_files: list[dict[str, Any]],
        model: str,
        rounds: int,
        variable_overrides: dict[str, Any],
        data_dictionary_config: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._abort_if_stale(_generation)
            load_project_env(REPO_ROOT)
            run_root, repo, _, dictionary = initialize_live_workspace(
                question=question,
                knowledge_files=knowledge_files,
                data_files=data_files,
                model=model,
                variable_overrides=variable_overrides,
                data_dictionary_config=data_dictionary_config,
            )
            self._abort_if_stale(_generation)
            self._update(
                _generation=_generation,
                status="running",
                stage="llm_bootstrap",
                message="已写入任务与数据，正在启动 LLM 闭环。",
                runRoot=str(run_root),
            )

            gateway_bundle = build_real_llm_control(repo, run_root, model=model)
            control = gateway_bundle["control"]
            control.prepare_initial_review_context(data_dictionary=dictionary)
            self._abort_if_stale(_generation)

            self._update(
                _generation=_generation,
                status="running",
                stage="round_review_requested",
                message="正在生成候选实验并请求审批。",
                currentRound=1,
            )
            control.request_experiment_selection_review()
            self._abort_if_stale(_generation)
            self._update(
                _generation=_generation,
                status="awaiting_approval",
                stage="approval_pending",
                message="候选实验已生成，等待人工审批。",
                currentRound=1,
            )
        except StaleSessionError:
            self._cleanup_if_stale(_generation)
        except Exception as exc:
            failure_path = LIVE_ROOT / "failure_report.json"
            failure_path.parent.mkdir(parents=True, exist_ok=True)
            failure_path.write_text(
                json.dumps(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._update(
                _generation=_generation,
                status="failed",
                stage="failed",
                message=f"真实闭环执行失败：{exc}",
            )

    def approve_candidate(
        self,
        *,
        candidate_id: str | None,
        human_notes: str | None,
        model_parameters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self._assert_not_busy()
        self._update(
            status="running",
            stage="experiment_execution",
            message="正在执行已批准的候选实验。",
        )
        return self._start_worker(
            self._run_candidate_execution,
            candidate_id=candidate_id,
            human_notes=human_notes,
            model_parameters=model_parameters or {},
        )

    def _run_candidate_execution(
        self,
        *,
        _generation: int,
        candidate_id: str | None,
        human_notes: str | None,
        model_parameters: dict[str, Any],
    ) -> None:
        try:
            self._abort_if_stale(_generation)
            repo = UnifiedStateRepository(LIVE_ROOT)
            control = self._build_control(repo)
            execution = control.approve_and_execute_candidate(
                candidate_id=candidate_id,
                human_notes=human_notes,
                auto_continue=False,
                model_parameters=model_parameters or None,
            )
            self._abort_if_stale(_generation)
            self._update(
                _generation=_generation,
                status="awaiting_round_decision",
                stage="round_review_requested",
                message=(
                    "本轮实验已完成，请输入整轮反馈并决定是否继续。"
                    if not execution.get("failure")
                    else f"本轮实验失败但已记录归因：{execution['failure']}。请基于失败结果决定是否继续下一轮。"
                ),
                currentRound=execution["protocol"].round_id,
            )
        except StaleSessionError:
            self._cleanup_if_stale(_generation)
        except Exception as exc:
            self._update(
                _generation=_generation,
                status="failed",
                stage="failed",
                message=f"实验执行失败：{exc}",
            )

    def reject_candidate(self, *, candidate_id: str | None, reason: str) -> dict[str, Any]:
        self._assert_not_busy()
        repo = UnifiedStateRepository(LIVE_ROOT)
        control = self._build_control(repo)
        result = control.reject_candidate(candidate_id=candidate_id, reason=reason)
        self._update(
            status="awaiting_approval",
            stage="approval_pending",
            message="已拒绝当前候选实验，请重新选择。",
            currentRound=self._current_round(),
        )
        return result

    def pause_current_stage(self, *, reason: str) -> dict[str, Any]:
        self._assert_not_busy()
        repo = UnifiedStateRepository(LIVE_ROOT)
        process_state = repo.load_process_state()
        control = self._build_control(repo)
        control.request_stop(phase=process_state.current_phase or "experiment_planning", reason=reason, pause=True)
        self._update(
            status="paused",
            stage="paused",
            message=reason or "当前流程已暂停。",
            currentRound=self._current_round(),
        )
        return self.snapshot()

    def record_round_decision(self, *, decision: str, human_feedback: str | None) -> dict[str, Any]:
        self._assert_not_busy()
        repo = UnifiedStateRepository(LIVE_ROOT)
        current_round = self._current_round()
        if decision == "stop":
            control = self._build_control(repo)
            dictionary = self._rebuild_dictionary(repo)
            control.record_round_decision(
                round_id=current_round,
                decision="stop",
                human_feedback=human_feedback,
                data_dictionary=dictionary,
            )
            self._update(
                status="completed",
                stage="completed",
                message="当前闭环已停止，状态已固化。",
                currentRound=current_round,
            )
            return self.snapshot()

        self._update(
            status="running",
            stage="next_round_planning",
            planning_status="candidate_plan_rebuilding",
            message="正在根据本轮反馈生成下一轮候选实验。",
            currentRound=current_round,
        )
        return self._start_worker(
            self._run_round_decision,
            round_id=current_round,
            decision=decision,
            human_feedback=human_feedback,
        )

    def _run_round_decision(self, *, _generation: int, round_id: int, decision: str, human_feedback: str | None) -> None:
        try:
            self._abort_if_stale(_generation)
            repo = UnifiedStateRepository(LIVE_ROOT)
            dictionary = self._rebuild_dictionary(repo)
            control = self._build_control(repo)
            control.record_round_decision(
                round_id=round_id,
                decision=decision,
                human_feedback=human_feedback,
                data_dictionary=dictionary,
            )
            self._abort_if_stale(_generation)
            repo = UnifiedStateRepository(LIVE_ROOT)
            process_state = repo.load_process_state()
            candidate_set = repo.load_candidate_experiments()
            next_round = max(candidate_set.round or 0, process_state.current_round, round_id + 1)
            self._update(
                _generation=_generation,
                status="awaiting_approval",
                stage="approval_pending",
                planning_status="candidate_plan_rebuilt",
                message=f"第 {next_round} 轮候选实验已生成，等待审批。",
                currentRound=next_round,
            )
        except StaleSessionError:
            self._cleanup_if_stale(_generation)
        except Exception as exc:
            self._update(
                _generation=_generation,
                status="failed",
                stage="failed",
                message=f"下一轮规划失败：{exc}",
            )


SESSION_MANAGER = LiveSessionManager()


class LiveWorkflowHandler(BaseHTTPRequestHandler):
    server_version = "ShadowTracingLiveServer/1.0"

    def _set_headers(self, status: int = HTTPStatus.OK, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_OPTIONS(self) -> None:
        self._set_headers()

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._write_json({"status": "ok", "service": "live_workflow_server"})
            return
        if self.path == "/api/session":
            self._write_json(SESSION_MANAGER.snapshot())
            return
        if self.path == "/api/failure-report":
            failure_path = LIVE_ROOT / "failure_report.json"
            if failure_path.exists():
                self._set_headers(status=HTTPStatus.OK, content_type="application/json; charset=utf-8")
                self.wfile.write(failure_path.read_bytes())
                return
            self._write_json({"message": "当前没有失败报告。"}, status=HTTPStatus.NOT_FOUND)
            return
        if self.path.startswith("/api/state/"):
            self._serve_state_file()
            return
        if self.path.startswith("/api/visualizations/"):
            self._serve_visualization_file()
            return
        self._write_json({"message": "Not Found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/session/reset":
            self._write_json(SESSION_MANAGER.reset())
            return
        if self.path == "/api/session/analyze-question":
            self._handle_analyze_question()
            return
        if self.path == "/api/session/inspect-data":
            self._handle_inspect_data()
            return
        if self.path == "/api/workflow/start":
            self._handle_start_workflow()
            return
        if self.path == "/api/workflow/approval":
            self._handle_approval_action()
            return
        if self.path == "/api/workflow/round-decision":
            self._handle_round_decision()
            return
        self._write_json({"message": "Not Found"}, status=HTTPStatus.NOT_FOUND)

    def _write_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        self._set_headers(status=status)
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _serve_state_file(self) -> None:
        file_name = Path(unquote(self.path.removeprefix("/api/state/"))).name
        if not file_name:
            self._write_json({"message": "缺少状态文件名。"}, status=HTTPStatus.BAD_REQUEST)
            return
        target_path = STATE_DIR / file_name
        if not target_path.exists():
            self._write_json({"message": "状态文件不存在。"}, status=HTTPStatus.NOT_FOUND)
            return
        self._set_headers(status=HTTPStatus.OK, content_type="application/json; charset=utf-8")
        self.wfile.write(target_path.read_bytes())

    def _serve_visualization_file(self) -> None:
        relative_path = unquote(self.path.removeprefix("/api/visualizations/")).lstrip("/")
        if not relative_path:
            self._write_json({"message": "缺少图像路径。"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            target_path = ensure_relative_to(LIVE_ROOT, LIVE_ROOT / relative_path)
        except PermissionError as exc:
            self._write_json({"message": str(exc)}, status=HTTPStatus.FORBIDDEN)
            return
        if not target_path.exists() or not target_path.is_file():
            self._write_json({"message": "图像文件不存在。"}, status=HTTPStatus.NOT_FOUND)
            return

        mime_type, _ = mimetypes.guess_type(target_path.name)
        self._set_headers(status=HTTPStatus.OK, content_type=mime_type or "application/octet-stream")
        self.wfile.write(target_path.read_bytes())

    def _read_json_body(self) -> dict[str, Any]:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("请求体不是合法 JSON。") from exc
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象。")
        return payload

    def _handle_analyze_question(self) -> None:
        try:
            payload = self._read_json_body()
            question = str(payload.get("question") or "").strip()
            model = str(payload.get("model") or "qwen-plus").strip() or "qwen-plus"
            if not question:
                raise ValueError("科学问题不能为空。")
            analysis = analyze_question(question, model)
            self._write_json(
                {
                    "status": "ok",
                    "analysis": analysis.model_dump(mode="json", exclude_none=True),
                }
            )
        except Exception as exc:
            self._write_json({"message": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _handle_start_workflow(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._write_json({"message": "启动接口仅支持 multipart/form-data。"}, status=HTTPStatus.BAD_REQUEST)
            return

        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        fields, uploaded_files = parse_multipart_form(content_type, body)
        question = (fields.get("question", [""])[0] or "").strip()
        model = ((fields.get("model", ["qwen-plus"])[0] or "qwen-plus")).strip() or "qwen-plus"
        rounds = int((fields.get("rounds", ["2"])[0] or "2"))
        x_variable = (fields.get("x_variable", [""])[0] or "").strip() or None
        y_variable = (fields.get("y_variable", [""])[0] or "").strip() or None
        question_type = (fields.get("question_type", [""])[0] or "").strip() or None
        raw_candidates = (fields.get("m_candidates", [""])[0] or "").strip()
        m_candidates = parse_m_candidates_payload(raw_candidates)
        data_dictionary_config = fields.get("data_dictionary_config", [""])[0] or None

        try:
            status = SESSION_MANAGER.start(
                question=question,
                knowledge_files=uploaded_files.get("knowledge_files", []),
                data_files=uploaded_files.get("data_files", []),
                model=model,
                rounds=rounds,
                variable_overrides=build_variable_override_payload(
                    x_variable=x_variable,
                    y_variable=y_variable,
                    m_candidates=m_candidates,
                    question_type=question_type,
                ),
                data_dictionary_config=parse_data_dictionary_config(data_dictionary_config),
            )
            self._write_json(status, status=HTTPStatus.ACCEPTED)
        except Exception as exc:
            self._write_json({"message": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _handle_inspect_data(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._write_json({"message": "数据检查接口仅支持 multipart/form-data。"}, status=HTTPStatus.BAD_REQUEST)
            return

        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        _, uploaded_files = parse_multipart_form(content_type, body)
        try:
            inspection = inspect_uploaded_data_files(uploaded_files.get("data_files", []))
            self._write_json({"status": "ok", "inspection": inspection}, status=HTTPStatus.OK)
        except Exception as exc:
            self._write_json({"message": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _handle_approval_action(self) -> None:
        try:
            payload = self._read_json_body()
            action = str(payload.get("action") or "approve").strip()
            candidate_id = str(payload.get("candidateId") or "").strip() or None
            human_notes = str(payload.get("humanNotes") or "").strip() or None
            model_parameters = payload.get("modelParameters")
            if model_parameters is not None and not isinstance(model_parameters, dict):
                raise ValueError("modelParameters 必须是对象。")

            if action in {"approve", "modify"}:
                status = SESSION_MANAGER.approve_candidate(
                    candidate_id=candidate_id,
                    human_notes=human_notes,
                    model_parameters=model_parameters if isinstance(model_parameters, dict) else None,
                )
            elif action == "reject":
                status = SESSION_MANAGER.reject_candidate(
                    candidate_id=candidate_id,
                    reason=human_notes or "人工要求重选候选实验。",
                )
            elif action == "pause":
                status = SESSION_MANAGER.pause_current_stage(reason=human_notes or "人工暂停当前实验流程。")
            else:
                raise ValueError("未知审批动作。")
            self._write_json(status, status=HTTPStatus.ACCEPTED if action in {"approve", "modify"} else HTTPStatus.OK)
        except Exception as exc:
            self._write_json({"message": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _handle_round_decision(self) -> None:
        try:
            payload = self._read_json_body()
            decision = str(payload.get("decision") or "").strip()
            human_feedback = str(payload.get("humanFeedback") or "").strip() or None
            if decision not in {"continue", "adjust", "stop"}:
                raise ValueError("decision 必须是 continue / adjust / stop 之一。")
            status = SESSION_MANAGER.record_round_decision(
                decision=decision,
                human_feedback=human_feedback,
            )
            self._write_json(status, status=HTTPStatus.ACCEPTED if decision != "stop" else HTTPStatus.OK)
        except Exception as exc:
            self._write_json({"message": str(exc)}, status=HTTPStatus.BAD_REQUEST)


def main() -> int:
    load_project_env(REPO_ROOT)
    server = ThreadingHTTPServer((HOST, PORT), LiveWorkflowHandler)
    print(f"[live-server] http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[live-server] stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
