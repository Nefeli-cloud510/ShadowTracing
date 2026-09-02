# LLM And RAG Interfaces

This document marks the current integration points that can be replaced with
real Bailian model and knowledge-base APIs.

## LLM Gateway

File:
- `core/llm_gateway.py`

Current behavior:
- Uses DashScope-compatible OpenAI client if `DASHSCOPE_API_KEY` is present.
- Falls back to local deterministic builders when the API is unavailable.

Recommended environment variables:
- `DASHSCOPE_API_KEY`: Bailian / DashScope model API key
- `BAILIAN_API_KEY`: optional alias, can be mapped to the same key

Current model entry:
- `LLMGateway(model="qwen-plus")`

Replacement point:
- Replace `LLMGateway._build_client()` if you want a custom Bailian SDK client.
- Keep `generate_structured()` unchanged so all role modules still return
  schema-validated JSON.

## Central Controller

File:
- `core/central_controller_llm.py`

Current behavior:
- Consumes `ReasoningPlannerInput`
- Produces `ReasoningPlannerOutput(planner_mode="llm")`

Replacement point:
- Keep `CentralControllerLLM.build()` unchanged.
- Replace only the gateway or the prompt if you want a stronger Bailian model.

## Scientific Interpreter

File:
- `core/scientific_interpreter_llm.py`

Current behavior:
- Runs after `evaluate_experiment()`
- Produces `InterpretationEnhancement`
- Writes back into hypothesis tree, uncertainties, experiment memory, and
  decision log

Replacement point:
- Keep `build_interpretations()` unchanged.
- Replace only gateway/prompt logic.

## RAG Service

File:
- `core/rag_service.py`

Current behavior:
- Lightweight local retrieval over:
- `state/*.json`
- `outputs/pdf_texts/*.txt`
- Optional external knowledge callback

Recommended environment variables:
- `BAILIAN_WORKSPACE_ID`: Bailian business workspace id
- `BAILIAN_KNOWLEDGE_AGENT_ID`: published knowledge-search service id (`agent_id`)
- `BAILIAN_KNOWLEDGE_AGENT_VERSION`: optional published version
- `BAILIAN_KNOWLEDGE_SEARCH_ENDPOINT`: optional explicit override; if absent the code derives
  `https://{workspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/indices/knowledge/search`
- `BAILIAN_API_KEY`: API key for external KB access if shared with model side

Replacement point:
- Implement `knowledge_base_search(query, max_results)` and pass it into
  `RAGService(...)`
- Or replace `search_bailian_knowledge_base()` directly

Expected callback return format:

```python
[
    {
        "id": "doc_001",
        "title": "paper or kb title",
        "excerpt": "retrieved snippet",
        "score": 0.91,
        "citation": "doi/url/internal_doc_id",
    }
]
```

## Hypothesis Proposer

File:
- `core/hypothesis_proposer_llm.py`

Current behavior:
- Reads planner input and RAG context
- Outputs focus features and guidance notes
- Influences next-round hypothesis growth through `planner_guidance` and
  reasoning traces

## Scientific Questioner

File:
- `core/scientific_questioner_llm.py`

Current behavior:
- Reads planner input and RAG context
- Produces challenge points and new uncertainties
- Injects new uncertainty records before next-round hypothesis generation

## Experiment Planner

File:
- `core/experiment_planner_llm.py`

Current behavior:
- Reads the human-approved candidate plus any existing protocol refinements
- Produces one extra `ProtocolRefinementSuggestion`
- Runs inside `approve_candidate()` before protocol mapping

Replacement point:
- Keep `ExperimentPlannerLLM.refine()` unchanged.
- Replace only the gateway/prompt logic if you want a real Bailian planner role.
- Output still flows through existing `ExperimentProtocol` mapping and Pydantic
  validation, so unsafe protocol text is not applied directly.

## Wiring Points

Execution-time interpreter hook:
- `core/control_unified.py`
- `approve_and_execute_candidate()`

Next-round planning hook:
- `core/control_unified.py`
- `_resume_next_round_planning()`

Protocol refinement hook:
- `core/control_unified.py`
- `approve_candidate()`

## Current Audit Outputs

The following files now carry the effects of LLM/RAG decisions:
- `state/experiment_memory.json`
- `state/decision_log.json`
- `state/planner_input.json`
- `state/planner_output.json`
- `state/hypothesis_tree.json`
- `state/uncertainties.json`
