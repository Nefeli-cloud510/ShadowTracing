from __future__ import annotations

import json
import re
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from core.runtime_config import (
    get_dasyscope_api_key,
    get_dasyscope_base_url,
    get_default_llm_model,
    load_project_env,
)


SchemaModelT = TypeVar("SchemaModelT", bound=BaseModel)


class LLMGateway:
    """Unified structured-output gateway for planner-side LLM roles."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
        client: Any | None = None,
    ) -> None:
        load_project_env()
        self.model = model or get_default_llm_model()
        self.api_key = api_key or get_dasyscope_api_key()
        self.base_url = base_url or get_dasyscope_base_url()
        self.temperature = temperature
        self.client = client or self._build_client()

    def is_available(self) -> bool:
        return self.client is not None

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[SchemaModelT],
        fallback_factory: Callable[[], SchemaModelT | dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> SchemaModelT:
        if self.client is None:
            if fallback_factory is None:
                raise RuntimeError("LLM client is unavailable and no fallback_factory was provided.")
            return self._coerce_response(response_model, fallback_factory())

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature if temperature is None else temperature,
            )
            content = response.choices[0].message.content or ""
            payload = _extract_json_payload(content)
            return response_model.model_validate(payload)
        except Exception:
            if fallback_factory is None:
                raise
            return self._coerce_response(response_model, fallback_factory())

    def _build_client(self) -> Any | None:
        if not self.api_key:
            return None
        try:
            from openai import OpenAI
        except Exception:
            return None
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    @staticmethod
    def _coerce_response(
        response_model: type[SchemaModelT],
        payload: SchemaModelT | dict[str, Any],
    ) -> SchemaModelT:
        if isinstance(payload, response_model):
            return payload
        return response_model.model_validate(payload)


def _extract_json_payload(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{[\s\S]*\}", stripped)
    if match is None:
        raise ValueError("LLM response does not contain a JSON object.")
    return json.loads(match.group(0))
