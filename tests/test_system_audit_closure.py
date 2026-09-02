import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

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


class SystemAuditClosureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / "data" / "raw").mkdir(parents=True, exist_ok=True)
        self.repository = UnifiedStateRepository(self.project_root)
        self._create_demo_data()
        self.task = ScientificTask(
            task_id="ST_AUDIT_001",
            payload=ScientificTaskPayload(
                research_question=ResearchQuestion(
                    text="DeltaDec 是否提供可重复验证的 Vsw 预测增量信息",
                    target="Vsw",
                    question_type="forecasting",
                    variables=VariableBinding(x="DeltaDec", y="Vsw", m_candidates=["By", "Bz", "Np"]),
                    keywords=["DeltaDec", "Vsw", "By", "Np"],
                    clarified=True,
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
                    max_rounds=10,
                    max_experiments_per_round=3,
                    resource_budget={
                        "token_budget": 100000,
                        "max_time_seconds_per_round": 300,
                        "max_candidates": 3,
                    },
                ),
                data_sources={
                    "omni": {"path": "data/raw/omni.csv", "time_column": "TIME"},
                    "lhaaso": {"path": "data/raw/lhaaso.csv", "time_column": "TIME"},
                },
            ),
        )
        self.dictionary = DataDictionary(
            dictionary_id="DICT_AUDIT_001",
            generated_at=datetime.now(),
            version="1.0",
            dataset_name="demo_audit",
            total_samples=128,
            time_column="TIME",
            time_format="YYYYMMDD",
            fields=[
                FieldDescriptor(field_name="TIME", data_type="int", physical_meaning="time"),
                FieldDescriptor(field_name="Vsw", data_type="float", physical_meaning="target", is_target=True),
                FieldDescriptor(field_name="By", data_type="float", physical_meaning="IMF By"),
                FieldDescriptor(field_name="Bz", data_type="float", physical_meaning="IMF Bz"),
                FieldDescriptor(field_name="Np", data_type="float", physical_meaning="Solar wind density"),
                FieldDescriptor(field_name="DeltaDec", data_type="float", physical_meaning="LHAASO DeltaDec"),
            ],
            target_candidates=["Vsw"],
            feature_candidates=["By", "Bz", "Np", "DeltaDec"],
        )
        self.repository.initialize_state_skeleton(
            self.task,
            initial_uncertainties=[
                UncertaintyRecord(
                    uncertainty_id="U01",
                    question="DeltaDec 的贡献是否独立于 By？",
                    description="需要区分独立增量与中介解释。",
                    related_hypotheses=[],
                    status="active",
                    priority="high",
                    created_at_round=0,
                    created_by="audit_test",
                ),
                UncertaintyRecord(
                    uncertainty_id="U02",
                    question="DeltaDec 的增益是否跨时间段稳定？",
                    description="需要检验滞后稳定性。",
                    related_hypotheses=[],
                    status="active",
                    priority="medium",
                    created_at_round=0,
                    created_by="audit_test",
                ),
            ],
            data_dictionary=self.dictionary,
            overwrite=True,
        )
        DecisionLayerService(self.repository).build_candidate_plan(task=self.task, data_dictionary=self.dictionary)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_demo_data(self) -> None:
        time_values = pd.date_range("2021-01-01", periods=48, freq="D")
        omni = pd.DataFrame(
            {
                "TIME": time_values.strftime("%Y%m%d"),
                "By": [(-1) ** i * (i % 5 + 1) for i in range(48)],
                "Bz": [(i % 7) - 3 for i in range(48)],
                "Np": [5.0 + (i % 4) * 0.5 for i in range(48)],
                "Vsw": [360 + i * 1.7 for i in range(48)],
            }
        )
        lhaaso = pd.DataFrame(
            {
                "TIME": time_values.strftime("%Y%m%d"),
                "DeltaDec": [0.08 * ((i % 6) - 3) + (0.02 if i % 9 == 0 else 0.0) for i in range(48)],
            }
        )
        omni.to_csv(self.project_root / "data" / "raw" / "omni.csv", index=False)
        lhaaso.to_csv(self.project_root / "data" / "raw" / "lhaaso.csv", index=False)

    def _run_two_rounds(self) -> dict[str, object]:
        control = HumanControlService(self.repository, project_root=self.project_root, run_shap=False)

        initial_review = control.request_experiment_selection_review()
        round1 = control.approve_and_execute_candidate(
            human_notes="round1 批准执行",
            auto_continue=False,
        )
        after_round1 = control.record_round_decision(
            round_id=round1["protocol"].round_id,
            decision="adjust",
            human_feedback="下一轮优先做更简单的验证型方案，并关注 By 与稳定性",
            data_dictionary=self.dictionary,
        )

        round2 = control.approve_and_execute_candidate(
            human_notes="round2 批准执行",
            auto_continue=False,
        )
        after_round2 = control.record_round_decision(
            round_id=round2["protocol"].round_id,
            decision="continue",
            data_dictionary=self.dictionary,
        )

        return {
            "initial_review": initial_review,
            "round1": round1,
            "after_round1": after_round1,
            "round2": round2,
            "after_round2": after_round2,
        }

    def test_two_round_closed_loop_transition(self) -> None:
        payload = self._run_two_rounds()

        round1_protocol = payload["round1"]["protocol"]
        round2_protocol = payload["round2"]["protocol"]

        self.assertEqual(payload["initial_review"]["status"], "awaiting_human_review")
        self.assertEqual(payload["round1"]["review"]["status"], "awaiting_round_decision")
        self.assertTrue(payload["round1"]["evaluation"].scientific.disagreement_updates)
        self.assertEqual(payload["after_round1"]["planning_status"], "candidate_plan_rebuilt")
        self.assertEqual(payload["after_round1"]["planner_input"].source_round_id, round1_protocol.round_id)
        self.assertTrue(payload["after_round1"]["planner_input"].recent_disagreement_updates)
        self.assertEqual(payload["after_round1"]["next_review"]["status"], "awaiting_human_review")

        self.assertGreater(round2_protocol.round_id, round1_protocol.round_id)
        self.assertEqual(payload["round2"]["review"]["status"], "awaiting_round_decision")
        self.assertTrue(payload["round2"]["evaluation"].scientific.disagreement_updates)
        self.assertEqual(payload["after_round2"]["planning_status"], "candidate_plan_rebuilt")
        self.assertEqual(payload["after_round2"]["planner_input"].source_round_id, round2_protocol.round_id)
        self.assertEqual(payload["after_round2"]["next_review"]["status"], "awaiting_human_review")

        candidate_set = self.repository.load_candidate_experiments()
        self.assertEqual(candidate_set.round, round2_protocol.round_id + 1)
        self.assertTrue(candidate_set.candidates)
        self.assertTrue(any(candidate.related_uncertainties for candidate in candidate_set.candidates))

    def test_state_and_logs_are_auditable_after_two_rounds(self) -> None:
        payload = self._run_two_rounds()
        round1_protocol = payload["round1"]["protocol"]
        round2_protocol = payload["round2"]["protocol"]

        expected_files = [
            self.repository.paths.hypothesis_tree,
            self.repository.paths.uncertainties,
            self.repository.paths.experiment_memory,
            self.repository.paths.decision_log,
            self.repository.paths.planner_input,
            self.repository.paths.planner_output,
        ]
        for path in expected_files:
            self.assertTrue(path.exists(), f"missing state file: {path}")

        tree = self.repository.load_hypothesis_tree()
        uncertainties = self.repository.load_uncertainties()
        experiment_memory = self.repository.load_experiment_memory()
        decision_log = self.repository.load_decision_log()
        planner_input = self.repository.load_planner_input()
        planner_output = self.repository.load_planner_output()

        self.assertEqual(tree.task_id, self.task.task_id)
        self.assertTrue(tree.nodes)
        node_index = tree.node_index()
        active_ids = set(tree.active_hypotheses)
        self.assertTrue(active_ids)
        self.assertTrue(active_ids.issubset(set(node_index)))
        self.assertEqual(tree.latest_update.event, "planner_output_applied")

        record_index = uncertainties.record_index()
        self.assertEqual(uncertainties.task_id, self.task.task_id)
        self.assertGreaterEqual(len(record_index), 2)
        self.assertTrue(any(record.history for record in uncertainties.records))
        for record in uncertainties.records:
            for hypothesis_id in record.related_hypotheses:
                self.assertIn(hypothesis_id, node_index)
            if record.resolution_status == "resolved":
                self.assertIsNotNone(record.resolving_experiment)
                self.assertIsNotNone(record.resolved_at_round)
            if record.resolution_status is not None:
                self.assertIn(record.resolution_status, {"resolved", "partially_resolved", "unresolved"})
        unresolved_ids = {record.uncertainty_id for record in uncertainties.records if record.status not in {"resolved", "deprecated"}}
        self.assertTrue(
            {item.uncertainty_id for item in uncertainties.priority_queue.queue}.issubset(unresolved_ids)
        )

        entry_index = experiment_memory.entry_index()
        self.assertIn(round1_protocol.experiment_id, entry_index)
        self.assertIn(round2_protocol.experiment_id, entry_index)
        self.assertTrue(entry_index[round1_protocol.experiment_id].reasoning_traces)
        self.assertTrue(entry_index[round2_protocol.experiment_id].reasoning_traces)

        decision_types = [entry.decision_type for entry in decision_log.decisions]
        self.assertGreaterEqual(decision_types.count("round_review_requested"), 2)
        self.assertGreaterEqual(decision_types.count("planner_input_prepared"), 2)
        self.assertGreaterEqual(decision_types.count("planner_output_generated"), 2)
        self.assertGreaterEqual(decision_types.count("planner_output_applied"), 2)
        self.assertIn("continue_next_round", decision_types)
        self.assertIn("round_adjusted", decision_types)

        self.assertEqual(planner_input.source_round_id, round2_protocol.round_id)
        self.assertEqual(planner_input.next_round_id, round2_protocol.round_id + 1)
        self.assertTrue(planner_input.recent_disagreement_updates)
        self.assertTrue(planner_input.unresolved_uncertainties)
        self.assertTrue(
            {item.uncertainty_id for item in planner_input.unresolved_uncertainties}.issubset(set(record_index))
        )
        self.assertTrue(
            {item.uncertainty_id for item in planner_input.recent_disagreement_updates}.issubset(set(record_index))
        )

        self.assertEqual(planner_output.source_round_id, planner_input.source_round_id)
        self.assertEqual(planner_output.next_round_id, planner_input.next_round_id)
        self.assertTrue(planner_output.candidate_supplements)
        self.assertTrue(planner_output.interpretation_enhancements)
        self.assertTrue(planner_output.protocol_refinements)
        candidate_set = self.repository.load_candidate_experiments()
        candidate_ids = {candidate.experiment_id for candidate in candidate_set.candidates}
        supplemented_ids = {
            item.candidate.experiment_id
            for item in planner_output.candidate_supplements
        }
        self.assertTrue(supplemented_ids.issubset(candidate_ids))


if __name__ == "__main__":
    unittest.main()
