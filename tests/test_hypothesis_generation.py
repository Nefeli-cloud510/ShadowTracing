import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.control_unified import HumanControlService
from core.decision_unified import DecisionLayerService
from core.hypothesis_generation import HypothesisGenerationResult, HypothesisGenerationService
from core.state_repository import UnifiedStateRepository
from core.unified_schema import (
    ClosureChecklistItem,
    DataDictionary,
    DataDictionarySummary,
    EvaluationSpec,
    FieldDescriptor,
    HypothesisNode,
    HypothesisQuestioningRecord,
    PlannerEvaluationSummary,
    ResearchQuestion,
    ReasoningPlannerInput,
    RoundHistoryEntry,
    ScientificConstraints,
    ScientificTask,
    ScientificTaskPayload,
    SupportHistoryEntry,
    UncertaintyRecord,
    VariableBinding,
)
from tests.test_decision_layer import (
    StubCandidateExperimentDesigner,
    StubCandidateExperimentWriter,
)


class HypothesisGenerationTest(unittest.TestCase):
    class _ProposalInjectingGenerator(HypothesisGenerationService):
        """Real generator that supplies the LLM proposal batch expected by build_tree."""

        def __init__(self, test_case: "HypothesisGenerationTest"):
            super().__init__()
            self.test_case = test_case

        def build_tree(self, **kwargs):
            planner_input = kwargs.get("planner_input")
            if planner_input is not None:
                planner_input.llm_hypothesis_proposals = self.test_case._llm_proposals(2)
                for proposal in planner_input.llm_hypothesis_proposals:
                    proposal["generated_at"] = datetime.now()
            return super().build_tree(**kwargs)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.repository = UnifiedStateRepository(self.project_root)
        self.task = ScientificTask(
            task_id="ST_GEN",
            payload=ScientificTaskPayload(
                research_question=ResearchQuestion(
                    text="DeltaDec 是否包含能够改善 Vsw 预测的独立信息",
                    target="Vsw",
                    question_type="forecasting",
                    variables=VariableBinding(x="DeltaDec", y="Vsw", m_candidates=["By", "Bz"]),
                    keywords=["DeltaDec", "Vsw"],
                    clarified=True,
                ),
                evaluation=EvaluationSpec(primary_metric="Pearson_r", secondary_metrics=["RMSE", "MAE"]),
                constraints=ScientificConstraints(
                    min_active_hypotheses=3,
                    max_hypotheses_per_level=3,
                    max_rounds=10,
                    max_experiments_per_round=3,
                ),
            ),
        )
        self.dictionary = DataDictionary(
            dictionary_id="DICT_GEN",
            generated_at=datetime.now(),
            version="1.0",
            dataset_name="demo",
            total_samples=128,
            time_column="TIME",
            time_format="YYYYMMDD",
            fields=[
                FieldDescriptor(field_name="TIME", data_type="int", physical_meaning="time"),
                FieldDescriptor(field_name="Vsw", data_type="float", physical_meaning="target", is_target=True),
                FieldDescriptor(field_name="By", data_type="float", physical_meaning="IMF By"),
                FieldDescriptor(field_name="Bz", data_type="float", physical_meaning="IMF Bz"),
                FieldDescriptor(field_name="Np", data_type="float", physical_meaning="solar wind density"),
                FieldDescriptor(field_name="DeltaDec", data_type="float", physical_meaning="LHAASO DeltaDec"),
            ],
            target_candidates=["Vsw"],
            feature_candidates=["By", "Bz", "Np", "DeltaDec"],
        )
        self.initial_uncertainties = [
            UncertaintyRecord(
                uncertainty_id="U01",
                question="LHAASO DeltaDec 的贡献是否独立于 IMF By？",
                description="需要区分独立增量与中介路径。",
                related_hypotheses=[],
                status="active",
                priority="high",
                created_at_round=0,
                created_by="tester",
            ),
            UncertaintyRecord(
                uncertainty_id="U02",
                question="LHAASO DeltaDec 的增益是否跨时间段稳定？",
                description="需要检验滞后与时间片稳定性。",
                related_hypotheses=[],
                status="active",
                priority="medium",
                created_at_round=0,
                created_by="tester",
            ),
        ]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _mark_round_closed(self, round_id: int) -> None:
        history = self.repository.load_round_history()
        entry = next((item for item in history.entries if item.round_id == round_id), None)
        if entry is None:
            entry = RoundHistoryEntry(round_id=round_id)
            history.entries.append(entry)
        entry.status = "completed"
        entry.gating_ready = True
        entry.closure_checklist = [
            ClosureChecklistItem(item_id="candidate_approval", label="候选实验已审批", completed=True),
            ClosureChecklistItem(
                item_id="experiment_execution",
                label="实验执行已完成或已失败归因",
                completed=True,
            ),
            ClosureChecklistItem(item_id="result_feedback", label="结果解释与反馈已写回", completed=True),
        ]
        entry.updated_at = datetime.now()
        history.last_updated = entry.updated_at
        self.repository.save_round_history(history)

    def _llm_proposals(self, round_no: int, *, prefixed: bool = True) -> list[dict]:
        statements = {
            "H1": "LHAASO DeltaDec 的贡献是否独立于 IMF By？",
            "H2": "LHAASO DeltaDec 主要通过 IMF By 起作用",
            "H3": "LHAASO DeltaDec 的增益是否跨时间段稳定？",
            "H4": "LHAASO DeltaDec 的独立贡献在特定 Np 条件下更强",
            "H5": "LHAASO DeltaDec 与 Vsw 的关联随太阳风状态变化",
        }
        prefixes = {display_id: f"第{round_no}轮假设{display_id}：" for display_id in statements}
        proposals = []
        for index in range(1, 6):
            display_id = f"H{index}"
            statement = statements[display_id]
            if prefixed:
                statement = f"{prefixes[display_id]}{statement}"
            evidence = [
                {
                    "evidence_type": "physical_reasoning",
                    "description": f"第{round_no}轮 {display_id} 的物理先验证据",
                    "source": "LLM提案",
                },
                {
                    "evidence_type": "literature",
                    "description": f"第{round_no}轮文献佐证：{display_id} 增量信息",
                    "source": "LLM提案",
                },
            ]
            proposals.append(
                {
                    "display_hypothesis_id": display_id,
                    "statement": statement,
                    "evidence_items": evidence,
                    "alternative_explanations": [f"第{round_no}轮{display_id}的替代解释"],
                    "predictions": [],
                    "falsification_conditions": [],
                    "activation_condition": "由系统按状态机管理",
                    "model": "qwen-test",
                    "source": "real_llm",
                    "generated_at": datetime.now(),
                }
            )
        return proposals

    def _planner_input(self, round_id: int, proposals: list[dict]) -> ReasoningPlannerInput:
        return ReasoningPlannerInput(
            task_id=self.task.task_id,
            source_round_id=round_id - 1,
            next_round_id=round_id,
            scientific_question=self.task.payload.research_question.text,
            target=self.task.payload.research_question.target,
            evaluation_summary=PlannerEvaluationSummary(round_id=round_id - 1),
            data_dictionary_summary=DataDictionarySummary(
                dictionary_id=self.dictionary.dictionary_id,
                dataset_name=self.dictionary.dataset_name,
                time_column=self.dictionary.time_column,
            ),
            llm_hypothesis_proposals=proposals,
        )

    def test_initialize_state_skeleton_generates_hypotheses_from_task_context(self) -> None:
        initialized = self.repository.initialize_state_skeleton(
            self.task,
            initial_uncertainties=self.initial_uncertainties,
            data_dictionary=self.dictionary,
            planner_input=self._planner_input(1, self._llm_proposals(1, prefixed=False)),
            overwrite=True,
        )

        tree = initialized["hypothesis_tree"]
        uncertainties = initialized["uncertainties"]
        self.assertGreaterEqual(len(tree.nodes), 3)
        self.assertEqual(tree.latest_update.event, "llm_hypothesis_generated")
        self.assertGreaterEqual(tree.tree_summary.active_count, 2)
        self.assertGreaterEqual(
            tree.tree_summary.pending_count,
            len(tree.nodes) - tree.tree_summary.active_count,
        )
        self.assertTrue(any("LHAASO DeltaDec" in node.statement for node in tree.nodes))
        self.assertTrue(any("target" in node.statement for node in tree.nodes))
        self.assertTrue(any("IMF By" in node.statement or "IMF Bz" in node.statement for node in tree.nodes))
        self.assertTrue(any("稳定" in node.statement or "时间" in node.statement for node in tree.nodes))
        self.assertTrue(all(record.related_hypotheses for record in uncertainties.records))
        primary_node = tree.nodes[0]
        self.assertIsNotNone(primary_node.generation_rationale)
        self.assertEqual(primary_node.generation_rationale.source_signals, [])

    def test_round_decision_extends_hypothesis_tree_from_planner_context(self) -> None:
        seed_nodes = [
            HypothesisNode(
                hypothesis_id="H1_canonical",
                display_hypothesis_id="H1",
                statement="DeltaDec 提供独立增量信息",
                level=1,
                status="active",
                support_score=0.6,
                activation_condition="always",
            ),
            HypothesisNode(
                hypothesis_id="H2_canonical",
                display_hypothesis_id="H2",
                statement="DeltaDec 主要通过 By 起作用",
                level=1,
                status="active",
                support_score=0.45,
                activation_condition="always",
            ),
            HypothesisNode(
                hypothesis_id="H3_canonical",
                display_hypothesis_id="H3",
                statement="DeltaDec 的时间稳定性待验证",
                level=1,
                status="active",
                support_score=0.4,
                activation_condition="always",
            ),
        ]
        seeded_uncertainties = [
            record.model_copy(
                update={
                    "related_hypotheses": [
                        "H_shadow_incremental_gain",
                        "H_by_mediated_path",
                    ]
                }
            )
            for record in self.initial_uncertainties
        ]
        self.repository.initialize_state_skeleton(
            self.task,
            initial_hypotheses=seed_nodes,
            initial_uncertainties=seeded_uncertainties,
            data_dictionary=self.dictionary,
            overwrite=True,
        )
        DecisionLayerService(
            self.repository,
            experiment_designer=StubCandidateExperimentDesigner(),
            experiment_writer=StubCandidateExperimentWriter(),
        ).build_candidate_plan(task=self.task, data_dictionary=self.dictionary)
        control = HumanControlService(
            self.repository,
            project_root=self.project_root,
            experiment_designer=StubCandidateExperimentDesigner(),
            experiment_writer=StubCandidateExperimentWriter(),
        )
        control.hypothesis_generator = self._ProposalInjectingGenerator(self)
        control.request_round_review(
            round_id=0,
            experiment_id="E_BOOTSTRAP",
            evaluation_summary={"pearson_r_delta": -0.02, "stable": False},
            hypothesis_assessments=[
                {
                    "hypothesis_id": self.repository.load_hypothesis_tree().active_hypotheses[0],
                    "support_before": 0.58,
                    "support_after": 0.46,
                    "status": "weakened",
                    "direction_matched": False,
                    "magnitude_matched": "partial",
                    "reason": "bootstrap weakening",
                }
            ],
            reasoning_traces=[
                {
                    "trace_id": "RT_BOOT",
                    "stage": "round_review_context",
                    "summary": "Np 条件路径和时间稳定性值得进一步拆分成新假设",
                    "related_uncertainties": ["U01", "U02"],
                }
            ],
        )

        self._mark_round_closed(round_id=0)
        recorded = control.record_round_decision(
            round_id=0,
            decision="adjust",
            human_feedback="下一轮优先检查 Np 条件路径，并验证时间稳定性",
            data_dictionary=self.dictionary,
        )

        self.assertTrue(recorded["hypothesis_generation"]["generated_node_ids"])
        self.assertEqual(recorded["planning_status"], "awaiting_hypothesis_confirmation")
        tree = self.repository.load_hypothesis_tree()
        generated_ids = set(recorded["hypothesis_generation"]["generated_node_ids"])
        generated_nodes = [node for node in tree.nodes if node.hypothesis_id in generated_ids]
        self.assertTrue(any("solar wind density" in node.statement for node in generated_nodes))
        self.assertTrue(any("稳定" in node.statement or "时间" in node.statement for node in tree.nodes))
        self.assertTrue(all(node.generation_rationale for node in generated_nodes))
        uncertainties = self.repository.load_uncertainties()
        # 链路口径：不确定性关联来自质询/挖掘阶段，回归生成只应保留既有关联，
        # 不要求自动给本轮新生成节点补链接。
        self.assertTrue(all(record.related_hypotheses for record in uncertainties.records))
        self.assertTrue(
            any(
                generated_ids.intersection(set(record.related_hypotheses))
                for record in uncertainties.records
            )
        )

        decision_log = self.repository.load_decision_log()
        self.assertIn("hypothesis_generated", [entry.decision_type for entry in decision_log.decisions])
        generation_entries = [entry for entry in decision_log.decisions if entry.decision_type == "hypothesis_generated"]
        self.assertTrue(generation_entries[-1].details["generated_hypotheses"])

    def test_round_two_inherits_round_end_support_status_history_without_old_questioning(self) -> None:
        service = HypothesisGenerationService()
        round_one = service.build_tree(
            task=self.task,
            data_dictionary=self.dictionary,
            planner_input=self._planner_input(1, self._llm_proposals(1)),
            current_round=1,
        ).tree
        self.assertEqual(len(round_one.nodes), 5)

        by_display = {node.display_hypothesis_id: node for node in round_one.nodes}
        round_end_state = {
            "H1": ("observing", 0.2206),
            "H2": ("active", 0.6072),
            "H3": ("active", 0.4126),
            "H4": ("active", 0.4126),
            "H5": ("observing", 0.3356),
        }
        for display_id, (status, support) in round_end_state.items():
            node = by_display[display_id]
            node.status = status
            node.support_score = round(support, 3)
            node.support_history.append(
                SupportHistoryEntry(round=1, score=round(support, 3), event="round_debrief")
            )
            node.questioning_records.append(
                HypothesisQuestioningRecord(
                    round=1,
                    impact_direction="mixed" if status == "active" else "downward",
                    impact_strength=0.40,
                    confidence=0.8,
                    rationale=f"{display_id} 第一轮质询结论",
                    support_before=0.4,
                    support_after=round(support, 3),
                    status=status,
                )
            )

        round_two = service.build_tree(
            task=self.task,
            data_dictionary=self.dictionary,
            planner_input=self._planner_input(2, self._llm_proposals(2)),
            existing_tree=round_one,
            current_round=2,
        ).tree

        by_display_two = {node.display_hypothesis_id: node for node in round_two.nodes}
        for display_id, (status, support) in round_end_state.items():
            inherited = by_display_two[display_id]
            self.assertEqual(inherited.status, status)
            self.assertAlmostEqual(inherited.support_score, round(support, 3))
            self.assertEqual(inherited.support_history[-1].event, "round_continuation")
            self.assertEqual(inherited.support_history[-1].round, 2)
            self.assertAlmostEqual(inherited.support_history[-1].score, round(support, 3))
            self.assertEqual(inherited.questioning_records, [])
            self.assertEqual(inherited.critiques, [])
            self.assertTrue(inherited.statement.startswith("第2轮"))
            self.assertIn("继承上一轮轮末状态", inherited.generation_rationale.summary)
            self.assertEqual(inherited.created_at_round, 1)
            self.assertEqual(len(inherited.evidence_items), 2)


if __name__ == "__main__":
    unittest.main()
