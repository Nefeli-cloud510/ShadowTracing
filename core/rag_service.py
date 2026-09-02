from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

from core.runtime_config import (
    get_bailian_knowledge_agent_id,
    get_bailian_knowledge_agent_version,
    get_bailian_workspace_id,
    get_dasyscope_api_key,
    get_knowledge_search_endpoint,
    load_project_env,
)
from core.unified_schema import ReasoningPlannerInput


class RAGEvidenceSnippet(BaseModel):
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    citation: str | None = None


class RAGContextBundle(BaseModel):
    query: str = Field(min_length=1)
    project_evidence: list[RAGEvidenceSnippet] = Field(default_factory=list)
    literature_evidence: list[RAGEvidenceSnippet] = Field(default_factory=list)
    external_evidence: list[RAGEvidenceSnippet] = Field(default_factory=list)

    def guidance_notes(self) -> list[str]:
        notes: list[str] = []
        if self.project_evidence:
            notes.append(f"rag_project:{self.project_evidence[0].excerpt}")
        if self.literature_evidence:
            notes.append(f"rag_literature:{self.literature_evidence[0].excerpt}")
        if self.external_evidence:
            notes.append(f"rag_external:{self.external_evidence[0].excerpt}")
        return notes


class RAGService:
    """Lightweight project/literature retrieval with explicit placeholders for future Bailian APIs."""

    def __init__(
        self,
        *,
        project_root: Path,
        knowledge_base_search=None,
    ) -> None:
        load_project_env(project_root)
        self.project_root = project_root
        self.knowledge_base_search = knowledge_base_search
        self.state_dir = self.project_root / "state"
        self.literature_dir = self.project_root / "outputs" / "pdf_texts"

        self.bailian_api_key = get_dasyscope_api_key()
        self.bailian_workspace_id = get_bailian_workspace_id()
        self.bailian_knowledge_agent_id = get_bailian_knowledge_agent_id()
        self.bailian_knowledge_agent_version = get_bailian_knowledge_agent_version()
        self.bailian_knowledge_endpoint = get_knowledge_search_endpoint() or self._default_knowledge_search_endpoint()

    def build_context_bundle(
        self,
        planner_input: ReasoningPlannerInput,
        *,
        max_project_results: int = 3,
        max_literature_results: int = 3,
        max_external_results: int = 3,
    ) -> RAGContextBundle:
        query = planner_input.merged_guidance_text() or planner_input.scientific_question
        return RAGContextBundle(
            query=query,
            project_evidence=self.search_project_knowledge(query, max_results=max_project_results),
            literature_evidence=self.search_literature_knowledge(query, max_results=max_literature_results),
            external_evidence=self.search_bailian_knowledge_base(query, max_results=max_external_results),
        )

    def search_project_knowledge(self, query: str, *, max_results: int = 5) -> list[RAGEvidenceSnippet]:
        files = [
            self.state_dir / "task.json",
            self.state_dir / "process.json",
            self.state_dir / "decision_log.json",
            self.state_dir / "experiment_memory.json",
            self.state_dir / "uncertainties.json",
            self.state_dir / "hypothesis_tree.json",
            self.state_dir / "planner_input.json",
            self.state_dir / "planner_output.json",
        ]
        return self._search_files(
            files=files,
            query=query,
            source_type="project_memory",
            max_results=max_results,
        )

    def search_literature_knowledge(self, query: str, *, max_results: int = 5) -> list[RAGEvidenceSnippet]:
        files = sorted(self.literature_dir.glob("*.txt")) if self.literature_dir.exists() else []
        return self._search_files(
            files=files,
            query=query,
            source_type="literature_memory",
            max_results=max_results,
        )

    def search_bailian_knowledge_base(self, query: str, *, max_results: int = 5) -> list[RAGEvidenceSnippet]:
        records: list[dict[str, object]] = []
        if self.knowledge_base_search is not None:
            records = self.knowledge_base_search(query, max_results=max_results)
        elif (
            self.bailian_api_key
            and self.bailian_knowledge_agent_id
            and self.bailian_knowledge_endpoint
        ):
            records = self._search_remote_knowledge_base(query, max_results=max_results)
        if not records:
            return []
        snippets: list[RAGEvidenceSnippet] = []
        for index, record in enumerate(records, start=1):
            snippets.append(
                RAGEvidenceSnippet(
                    source_type="bailian_knowledge_base",
                    source_id=record.get("id", f"kb_{index}"),
                    title=record.get("title", f"Bailian KB Result {index}"),
                    excerpt=record.get("excerpt", ""),
                    score=float(record.get("score", 0.5)),
                    citation=record.get("citation"),
                )
            )
        return snippets

    def _search_remote_knowledge_base(self, query: str, *, max_results: int) -> list[dict[str, object]]:
        payload = {
            "agent_id": self.bailian_knowledge_agent_id,
            "query": query,
            "images": [],
        }
        if self.bailian_knowledge_agent_version:
            payload["agent_version"] = self.bailian_knowledge_agent_version
        request = urllib.request.Request(
            self.bailian_knowledge_endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.bailian_api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, ValueError):
            return []
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, dict):
            return []
        if parsed.get("success") is False:
            return []
        data = parsed.get("data")
        if isinstance(data, dict) and isinstance(data.get("nodes"), list):
            return [
                self._normalize_remote_node(item)
                for item in data["nodes"][:max_results]
                if isinstance(item, dict)
            ]
        return []

    def _default_knowledge_search_endpoint(self) -> str | None:
        if not self.bailian_workspace_id:
            return None
        return (
            f"https://{self.bailian_workspace_id}.cn-beijing.maas.aliyuncs.com"
            "/api/v1/indices/knowledge/search"
        )

    @staticmethod
    def _normalize_remote_node(node: dict[str, object]) -> dict[str, object]:
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        doc_name = metadata.get("doc_name") if isinstance(metadata, dict) else None
        title = metadata.get("title") if isinstance(metadata, dict) else None
        content = metadata.get("content") if isinstance(metadata, dict) else None
        doc_id = metadata.get("doc_id") if isinstance(metadata, dict) else None
        return {
            "id": str(doc_id or metadata.get("_id") or "kb_node"),
            "title": str(title or doc_name or "Bailian Knowledge Node"),
            "excerpt": str(content or node.get("text") or ""),
            "score": float(node.get("score", metadata.get("_score", 0.5) if isinstance(metadata, dict) else 0.5)),
            "citation": metadata.get("doc_url") if isinstance(metadata, dict) else None,
        }

    def _search_files(
        self,
        *,
        files: list[Path],
        query: str,
        source_type: str,
        max_results: int,
    ) -> list[RAGEvidenceSnippet]:
        keywords = _extract_keywords(query)
        scored: list[RAGEvidenceSnippet] = []
        for file_path in files:
            if not file_path.exists():
                continue
            text = _safe_read_text(file_path)
            if not text:
                continue
            score = _keyword_score(text, keywords)
            if score <= 0:
                continue
            scored.append(
                RAGEvidenceSnippet(
                    source_type=source_type,
                    source_id=file_path.stem,
                    title=file_path.name,
                    excerpt=_best_excerpt(text, keywords),
                    score=min(score, 1.0),
                    citation=str(file_path.relative_to(self.project_root)).replace("\\", "/"),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:max_results]


def _safe_read_text(file_path: Path) -> str:
    try:
        raw = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = file_path.read_text(encoding="utf-8", errors="ignore")
    if file_path.suffix == ".json":
        try:
            return json.dumps(json.loads(raw), ensure_ascii=False)
        except json.JSONDecodeError:
            return raw
    return raw


def _extract_keywords(query: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]+", query)
    keywords = [token for token in tokens if len(token) >= 2]
    return list(dict.fromkeys(keywords))


def _keyword_score(text: str, keywords: list[str]) -> float:
    lowered = text.lower()
    matched = sum(1 for keyword in keywords if keyword.lower() in lowered)
    if not keywords:
        return 0.0
    return round(matched / len(keywords), 4)


def _best_excerpt(text: str, keywords: list[str], *, max_length: int = 180) -> str:
    lowered = text.lower()
    for keyword in keywords:
        index = lowered.find(keyword.lower())
        if index >= 0:
            start = max(0, index - 40)
            end = min(len(text), index + max_length - 40)
            return " ".join(text[start:end].split())
    return " ".join(text[:max_length].split())
