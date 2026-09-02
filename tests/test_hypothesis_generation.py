import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.control_unified import HumanControlService
from core.decision_unified import DecisionLayerService
from core.state_repository import UnifiedStateRepository
from core.unified_schema import (
    DataDictionary,
    EvaluationSpec,
    FieldDescriptor,
    ResearchQuestion,
    ScientificConstraints,
    ScientificTask,
    ScientificTaskPayload,
    UncertaintyRecord,
    VariableBinding,
)


class HypothesisGenerationTest(unittest.TestCase):
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
                question="DeltaDec 的贡献是否独立于 By？",
                description="需要区分独立增量与中介路径。",
                related_hypotheses=[],
                status="active",
                priority="high",
                created_at_round=0,
                created_by="tester",
            ),
            UncertaintyRecord(
                uncertainty_id="U02",
                question="DeltaDec 的增益是否跨时间段稳定？",
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

    def test_initialize_state_skeleton_generates_hypotheses_from_task_context(self) -> None:
        initialized = self.repository.initialize_state_skeleton(
            self.task,
            initial_uncertainties=self.initial_uncertainties,
            data_dictionary=self.dictionary,
            overwrite=True,
        )

        tree = initialized["hypothesis_tree"]
        uncertainties = initialized["uncertainties"]
        self.assertGreaterEqual(len(tree.nodes), 3)
        self.assertEqual(tree.latest_update.event, "hypothesis_generated")
        self.assertGreaterEqual(tree.tree_summary.active_count, 3)
        self.assertTrue(any("DeltaDec" in node.statement for node in tree.nodes))
        self.assertTrue(any("Vsw" in node.statement for node in tree.nodes))
        self.assertTrue(any("By" in node.statement or "Bz" in node.statement for node in tree.nodes))
        self.assertTrue(any("稳定" in node.statement or "时间" in node.statement for node in tree.nodes))
        self.assertTrue(all(record.related_hypotheses for record in uncertainties.records))
        primary_node = tree.nodes[0]
        self.assertIsNotNone(primary_node.generation_rationale)
        self.assertTrue(primary_node.generation_rationale.source_signals)

    def test_round_decision_extends_hypothesis_tree_from_planner_context(self) -> None:
        self.repository.initialize_state_skeleton(
            self.task,
            initial_uncertainties=self.initial_uncertainties,
            data_dictionary=self.dictionary,
            overwrite=True,
        )
        DecisionLayerService(self.repository).build_candidate_plan(task=self.task, data_dictionary=self.dictionary)
        control = HumanControlService(self.repository, project_root=self.project_root)
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

        recorded = control.record_round_decision(
            round_id=0,
            decision="adjust",
            human_feedback="下一轮优先检查 Np 条件路径，并验证时间稳定性",
            data_dictionary=self.dictionary,
        )

        self.assertTrue(recorded["hypothesis_generation"]["generated_node_ids"])
        tree = self.repository.load_hypothesis_tree()
        generated_ids = set(recorded["hypothesis_generation"]["generated_node_ids"])
        generated_nodes = [node for node in tree.nodes if node.hypothesis_id in generated_ids]
        self.assertTrue(any("Np" in node.statement for node in generated_nodes))
        self.assertTrue(any("稳定" in node.statement or "时间" in node.statement for node in tree.nodes))
        self.assertTrue(all(node.generation_rationale for node in generated_nodes))
        self.assertTrue(any(
            any(signal.signal_type in {"human_feedback", "human_feedback_entry", "reasoning_trace"} for signal in node.generation_rationale.source_signals)
            for node in generated_nodes
        ))
        uncertainties = self.repository.load_uncertainties()
        self.assertTrue(any(generated_ids.intersection(set(record.related_hypotheses)) for record in uncertainties.records))

        decision_log = self.repository.load_decision_log()
        self.assertIn("hypothesis_generated", [entry.decision_type for entry in decision_log.decisions])
        generation_entries = [entry for entry in decision_log.decisions if entry.decision_type == "hypothesis_generated"]
        self.assertTrue(generation_entries[-1].details["generated_hypotheses"])


if __name__ == "__main__":
    unittest.main()
