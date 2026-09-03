from __future__ import annotations

from pydantic import BaseModel, Field

from core.llm_gateway import LLMGateway
from core.rag_service import RAGContextBundle
from core.unified_schema import ReasoningPlannerInput


class ProposedUncertainty(BaseModel):
    uncertainty_id: str | None = None
    question: str = Field(min_length=1)
    description: str = Field(min_length=1)
    priority: str = Field(default="medium", min_length=1)


class ScientificQuestionerResponse(BaseModel):
    challenge_points: list[str] = Field(default_factory=list)
    guidance_notes: list[str] = Field(default_factory=list)
    proposed_uncertainties: list[ProposedUncertainty] = Field(default_factory=list)


class ScientificQuestionerLLM:
    """LLM-backed scientific questioner that turns evidence gaps into explicit uncertainties."""

    SYSTEM_PROMPT = """你是“逐影 Shadow Tracing”的科学质询者。

你的任务是识别当前闭环中的证据缺口、替代解释和仍需验证的问题，并输出结构化 JSON。
必须充分利用全部假设树节点、竞争假设之间的分歧、证据缺口、参数敏感性、模型残差和失败归因，尽量批量产出 6-10 条具有物理意义的不确定性。
所有变量名称必须严格来自 planner_input.data_dictionary_summary 中已有的字段，不允许发明数据表里不存在的新变量。
不要直接修改状态文件，只给出 challenge_points、guidance_notes、proposed_uncertainties。"""

    def __init__(self, *, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway or LLMGateway()

    def question(
        self,
        *,
        planner_input: ReasoningPlannerInput,
        rag_context: RAGContextBundle,
    ) -> ScientificQuestionerResponse:
        return self.gateway.generate_structured(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=(
                f"planner_input={planner_input.to_central_controller_payload()}\n"
                f"rag_notes={rag_context.guidance_notes()}\n"
                "allowed_fields="
                f"{planner_input.data_dictionary_summary.feature_candidates + planner_input.data_dictionary_summary.target_candidates + [planner_input.data_dictionary_summary.time_column]}\n"
                "请输出 challenge_points、guidance_notes、proposed_uncertainties。"
                "proposed_uncertainties 应尽量覆盖多条假设分歧与剩余问题，而不是只给 1-2 条泛化问题。"
            ),
            response_model=ScientificQuestionerResponse,
            fallback_factory=lambda: self._fallback(planner_input, rag_context),
        )

    @staticmethod
    def _fallback(
        planner_input: ReasoningPlannerInput,
        rag_context: RAGContextBundle,
    ) -> ScientificQuestionerResponse:
        uncertainties: list[ProposedUncertainty] = []
        challenges: list[str] = []
        notes: list[str] = []
        focus_fields = planner_input.data_dictionary_summary.feature_candidates[:8]
        target = planner_input.target
        hypothesis_snapshots = planner_input.active_hypotheses[:8]
        disagreement_updates = planner_input.recent_disagreement_updates[:6]
        reasoning_traces = planner_input.recent_reasoning_traces[-6:]
        if planner_input.evaluation_summary.stable is False:
            focus = focus_fields[0] if focus_fields else target
            challenges.append(f"上一轮结果稳定性不足，需要继续检验 {focus} 对 {target} 的作用是否只在局部时间窗成立。")
            uncertainties.append(
                ProposedUncertainty(
                    question=f"{focus} 对 {target} 的增益是否只在局部时间窗口成立？",
                    description=f"需要围绕 {focus} 与 {target} 的关系增加时间片或稳定性验证，避免把局部提升误判为普遍规律。",
                    priority="high",
                )
            )
        for index, snapshot in enumerate(hypothesis_snapshots, start=1):
            focus = focus_fields[(index - 1) % len(focus_fields)] if focus_fields else target
            uncertainties.append(
                ProposedUncertainty(
                    question=f"{snapshot.hypothesis_id} 关于 {focus} 与 {target} 的解释是否仍受未建模条件约束？",
                    description=f"需要针对假设 {snapshot.hypothesis_id} 检查 {focus} 与 {target} 的关系是否受额外条件、阶段变化或隐藏竞争解释影响。",
                    priority="high" if index <= 4 else "medium",
                )
            )
        for update in disagreement_updates:
            challenges.append(f"{update.uncertainty_id} 仍未完全解决，应继续设计区分性验证。")
            uncertainties.append(
                ProposedUncertainty(
                    question=f"{update.uncertainty_id} 的主导解释是否会因参数敏感性或残差结构而反转？",
                    description=f"需要继续围绕 {update.uncertainty_id} 做参数敏感性、残差来源与竞争解释验证，避免当前领先假设被偶然噪声主导。",
                    priority="high",
                )
            )
        for index, trace in enumerate(reasoning_traces, start=1):
            if not trace.summary:
                continue
            focus = focus_fields[(index - 1) % len(focus_fields)] if focus_fields else target
            uncertainties.append(
                ProposedUncertainty(
                    question=f"{focus} 对 {target} 的解释是否遗漏了日志中提示的残差或失败归因？",
                    description=f"需要结合推理日志“{trace.summary[:80]}”进一步确认 {focus} 是否只是代理变量，或是否存在未覆盖残差来源。",
                    priority="medium",
                )
            )
        if rag_context.project_evidence:
            notes.append(f"questioner_project:{rag_context.project_evidence[0].excerpt}")
        if rag_context.literature_evidence:
            notes.append(f"questioner_literature:{rag_context.literature_evidence[0].excerpt}")
        if not uncertainties:
            focus = focus_fields[0] if focus_fields else target
            uncertainties.append(
                ProposedUncertainty(
                    question=f"当前关于 {focus} 与 {target} 的主假设是否存在尚未显式建模的替代解释？",
                    description=f"需要围绕现有字段 {focus} 与 {target} 补充一个竞争性不确定性，避免闭环只沿单一路径收敛。",
                    priority="medium",
                )
            )
        return ScientificQuestionerResponse(
            challenge_points=(challenges or ["当前证据仍需通过竞争解释和稳健性验证进一步约束。"])[:10],
            guidance_notes=notes,
            proposed_uncertainties=uncertainties[:10],
        )
