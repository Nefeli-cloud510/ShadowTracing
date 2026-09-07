from __future__ import annotations

import base64
import json
import re
from pathlib import Path
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
        allow_fallback: bool = True,
    ) -> None:
        load_project_env()
        self.model = model or get_default_llm_model()
        self.api_key = api_key or get_dasyscope_api_key()
        self.base_url = base_url or get_dasyscope_base_url()
        self.temperature = temperature
        self.allow_fallback = allow_fallback
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
        payload_fixer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        temperature: float | None = None,
        image_paths: list[str] | None = None,
    ) -> SchemaModelT:
        if self.client is None:
            if fallback_factory is None or not self.allow_fallback:
                raise RuntimeError("LLM client is unavailable for the real workflow.")
            return self._coerce_response(response_model, fallback_factory())

        try:
            user_content: Any = user_prompt
            if image_paths:
                content_parts: list[dict[str, Any]] = [
                    {"type": "text", "text": user_prompt},
                ]
                for image_path in image_paths:
                    encoded, media_type = _encode_image(image_path)
                    content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{encoded}",
                            },
                        }
                    )
                user_content = content_parts
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=self.temperature if temperature is None else temperature,
            )
            content = response.choices[0].message.content or ""
            payload = _extract_json_payload(content)
            if payload_fixer is not None:
                payload = payload_fixer(payload)
            return response_model.model_validate(payload)
        except Exception:
            if fallback_factory is None or not self.allow_fallback:
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
            timeout=300,
            max_retries=1,
        )

    @staticmethod
    def _coerce_response(
        response_model: type[SchemaModelT],
        payload: SchemaModelT | dict[str, Any],
    ) -> SchemaModelT:
        if isinstance(payload, response_model):
            return payload
        return response_model.model_validate(payload)


def _encode_image(path: str) -> tuple[str, str]:
    image_path = Path(path)
    if not image_path.is_file():
        raise FileNotFoundError(f"Report chart not found for LLM analysis: {path}")
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(image_path.suffix.lower(), "image/png")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return encoded, media_type


def _extract_json_payload(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{[\s\S]*\}", stripped)
    if match is None:
        raise ValueError("LLM response does not contain a JSON object.")
    return json.loads(match.group(0))
