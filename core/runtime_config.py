from __future__ import annotations

import os
import re
import json
from pathlib import Path


DEFAULT_DASHSCOPE_BASE_URL = (
    "https://llm-jz60biyiqkkwzssm.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)
DEFAULT_ROLE_MODELS = {
    "hypothesis_proposer": "qwen-plus",
    "scientific_questioner": "qwen-plus",
    "central_controller": "qwen3.8-max",
    "experiment_planner": "qwen-plus",
    "scientific_interpreter": "qwen3.8-max",
}


def load_project_env(start_path: Path | None = None) -> Path | None:
    """Load .env from the nearest project root without overriding existing env vars."""
    for env_path in _candidate_env_paths(start_path):
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
        return env_path
    return None


def get_runtime_setting(name: str, default: str | None = None) -> str | None:
    load_project_env()
    return os.getenv(name, default)


def get_dasyscope_api_key() -> str | None:
    return get_runtime_setting("DASHSCOPE_API_KEY") or get_runtime_setting("BAILIAN_API_KEY")


def get_dasyscope_base_url() -> str:
    return get_runtime_setting("DASHSCOPE_BASE_URL", DEFAULT_DASHSCOPE_BASE_URL) or DEFAULT_DASHSCOPE_BASE_URL


def get_default_llm_model() -> str:
    return get_runtime_setting("BAILIAN_MODEL", "qwen-plus") or "qwen-plus"


def get_llm_role_models() -> dict[str, str]:
    default_model = get_default_llm_model()
    role_models = {
        role: model or default_model for role, model in DEFAULT_ROLE_MODELS.items()
    }
    raw_mapping = get_runtime_setting("BAILIAN_ROLE_MODELS")
    if raw_mapping:
        try:
            parsed = json.loads(raw_mapping)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for role, model in parsed.items():
                if isinstance(role, str) and isinstance(model, str) and role in role_models:
                    role_models[role] = model
    for role in list(role_models):
        env_key = f"BAILIAN_MODEL_{role.upper()}"
        override = get_runtime_setting(env_key)
        if override:
            role_models[role] = override
    return role_models


def get_llm_model_for_role(role: str) -> str:
    return get_llm_role_models().get(role, get_default_llm_model())


def get_knowledge_base_id() -> str | None:
    return get_runtime_setting("BAILIAN_KNOWLEDGE_BASE_ID")


def get_knowledge_search_endpoint() -> str | None:
    return get_runtime_setting("BAILIAN_KNOWLEDGE_SEARCH_ENDPOINT")


def get_bailian_workspace_id() -> str | None:
    raw = get_runtime_setting("BAILIAN_WORKSPACE_ID")
    if not raw:
        return None
    match = re.search(r"https?://([^./]+)\.cn-beijing\.maas\.aliyuncs\.com", raw)
    if match:
        return match.group(1)
    host_match = re.search(r"^([^./]+)\.cn-beijing\.maas\.aliyuncs\.com", raw)
    if host_match:
        return host_match.group(1)
    if "/" not in raw and "." not in raw:
        return raw
    return raw


def get_bailian_knowledge_agent_id() -> str | None:
    return get_runtime_setting("BAILIAN_KNOWLEDGE_AGENT_ID") or get_knowledge_base_id()


def get_bailian_knowledge_agent_version() -> str | None:
    return get_runtime_setting("BAILIAN_KNOWLEDGE_AGENT_VERSION")


def real_api_tests_enabled() -> bool:
    value = (get_runtime_setting("ENABLE_REAL_API_TESTS", "0") or "0").lower()
    return value in {"1", "true", "yes", "on"}


def _candidate_env_paths(start_path: Path | None) -> list[Path]:
    anchor = start_path or Path(__file__).resolve()
    if anchor.is_file():
        anchor = anchor.parent
    candidates: list[Path] = []
    for parent in [anchor, *anchor.parents]:
        candidates.append(parent / ".env")
    return candidates
