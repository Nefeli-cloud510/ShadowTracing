from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from core.hypothesis_proposer_llm import HypothesisProposerLLM, HypothesisProposerResponse
from core.rag_service import RAGContextBundle
from core.scientific_questioner_llm import (
    ScientificQuestionerLLM,
    ScientificQuestionerResponse,
)
from core.unified_schema import ReasoningPlannerInput


@dataclass
class ParallelReasoningBundle:
    proposer: HypothesisProposerResponse
    questioner: ScientificQuestionerResponse


class ParallelReasoningOrchestrator:
    """Run independent planner-side LLM roles concurrently and collect structured outputs."""

    def __init__(
        self,
        *,
        hypothesis_proposer: HypothesisProposerLLM,
        scientific_questioner: ScientificQuestionerLLM,
        max_workers: int = 2,
    ) -> None:
        self.hypothesis_proposer = hypothesis_proposer
        self.scientific_questioner = scientific_questioner
        self.max_workers = max(1, max_workers)

    def run(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        rag_context: RAGContextBundle,
        mined_candidates: list[dict[str, object]] | None = None,
    ) -> ParallelReasoningBundle:
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            proposer_future = executor.submit(
                self.hypothesis_proposer.propose,
                planner_input=planner_input,
                rag_context=rag_context,
            )
            questioner_future = executor.submit(
                self.scientific_questioner.question,
                planner_input=planner_input,
                rag_context=rag_context,
                mined_candidates=mined_candidates,
            )
            return ParallelReasoningBundle(
                proposer=proposer_future.result(),
                questioner=questioner_future.result(),
            )
