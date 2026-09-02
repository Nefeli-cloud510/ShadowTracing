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
    HypothesisNode,
    ResearchQuestion,
    ScientificConstraints,
    ScientificTask,
    ScientificTaskPayload,
    UncertaintyRecord,
    VariableBinding,
)


class HumanControlFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / "data" / "raw").mkdir(parents=True, exist_ok=True)
        self.repository = UnifiedStateRepository(self.project_root)
        self._create_demo_data()
        self.task = ScientificTask(
            task_id="ST_300",
            payload=ScientificTaskPayload(
                research_question=ResearchQuestion(
                    text="DeltaDec 是否包含能够改善 Vsw 预测的独立信息",
                    target="Vsw",
                    question_type="forecasting",
                    variables=VariableBinding(x="DeltaDec", y="Vsw", m_candidates=["By", "Bz"]),
                    keywords=["DeltaDec", "Vsw"],
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
            dictionary_id="DICT_300",
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
                FieldDescriptor(field_name="DeltaDec", data_type="float", physical_meaning="LHAASO DeltaDec"),
            ],
            target_candidates=["Vsw"],
            feature_candidates=["By", "Bz", "DeltaDec"],
        )
        self.repository.initialize_state_skeleton(
            self.task,
            initial_hypotheses=[
                HypothesisNode(
                    hypothesis_id="H1",
                    statement="DeltaDec 提供独立增量信息",
                    level=1,
                    status="active",
                    support_score=0.6,
                    activation_condition="always",
                ),
                HypothesisNode(
                    hypothesis_id="H2",
                    statement="DeltaDec 主要通过 By 起作用",
                    level=1,
                    status="active",
                    support_score=0.45,
                    activation_condition="always",
                ),
            ],
            initial_uncertainties=[
                UncertaintyRecord(
                    uncertainty_id="U01",
                    question="DeltaDec 的贡献是否独立于 By？",
                    description="需要区分独立增量与中介解释。",
                    related_hypotheses=["H1", "H2"],
                    status="active",
                    priority="high",
                    created_at_round=1,
                    created_by="tester",
                ),
                UncertaintyRecord(
                    uncertainty_id="U02",
                    question="DeltaDec 的增益是否跨时间段稳定？",
                    description="需要检验滞后稳定性。",
                    related_hypotheses=["H1"],
                    status="active",
                    priority="medium",
                    created_at_round=1,
                    created_by="tester",
                ),
            ],
            overwrite=True,
        )
        uncertainties = self.repository.load_uncertainties()
        uncertainties.current_round = 1
        self.repository.save_uncertainties(uncertainties)
        DecisionLayerService(self.repository).build_candidate_plan(task=self.task, data_dictionary=self.dictionary)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_demo_data(self) -> None:
        time_values = pd.date_range("2021-01-01", periods=36, freq="D")
        omni = pd.DataFrame(
            {
                "TIME": time_values.strftime("%Y%m%d"),
                "By": [(-1) ** i * (i % 5 + 1) for i in range(36)],
                "Bz": [(i % 7) - 3 for i in range(36)],
                "Vsw": [350 + i * 2 for i in range(36)],
            }
        )
        lhaaso = pd.DataFrame(
            {
                "TIME": time_values.strftime("%Y%m%d"),
                "DeltaDec": [0.1 * ((i % 6) - 3) for i in range(36)],
            }
        )
        omni.to_csv(self.project_root / "data" / "raw" / "omni.csv", index=False)
        lhaaso.to_csv(self.project_root / "data" / "raw" / "lhaaso.csv", index=False)

    def test_request_review_and_approve_top_candidate(self) -> None:
        control = HumanControlService(self.repository, project_root=self.project_root)
        review_payload = control.request_experiment_selection_review()
        self.assertEqual(review_payload["status"], "awaiting_human_review")
        self.assertEqual(review_payload["current_phase"], "experiment_planning")
        self.assertEqual(review_payload["current_step"], "step_4")

        protocol = control.approve_candidate(
            human_notes="同意先执行最高 utility 候选实验",
            auto_continue=False,
            model_parameters={"alpha": 0.2, "l1_ratio": 0.6},
        )
        self.assertEqual(protocol.task_id, "ST_300")
        self.assertEqual(protocol.source_candidate_id, protocol.experiment_id)
        self.assertTrue(protocol.hypothesis_predictions)
        self.assertTrue(protocol.target_uncertainties)
        self.assertTrue(protocol.disagreement_context)
        self.assertEqual(protocol.steps[0].action, "resolve_disagreement")
        self.assertIn("targets_uncertainty:U01", protocol.notes)
        baseline_step = next(step for step in protocol.steps if step.action == "run_model" and step.parameters.get("label") == "baseline")
        self.assertEqual(baseline_step.parameters["label"], "baseline")
        self.assertTrue((self.project_root / "config" / "latest_protocol.json").exists())

        process_state = self.repository.load_process_state()
        self.assertEqual(process_state.current_stage, "protocol_ready")
        self.assertEqual(process_state.current_step, "step_5")
        self.assertEqual(
            process_state.phases["experiment_planning"].steps["step_4"].status,
            "completed",
        )

        decision_log = self.repository.load_decision_log()
        self.assertEqual(len(decision_log.decisions), 3)
        self.assertEqual(decision_log.decisions[0].decision_type, "experiment_selection_requested")
        self.assertEqual(decision_log.decisions[1].decision_type, "experiment_approved")
        self.assertEqual(decision_log.decisions[2].decision_type, "protocol_generated")

    def test_reject_candidate_updates_state_and_candidate_set(self) -> None:
        control = HumanControlService(self.repository, project_root=self.project_root)
        control.request_experiment_selection_review()
        rejected = control.reject_candidate(reason="该候选与当前判断不一致")

        self.assertEqual(rejected["status"], "rejected")
        process_state = self.repository.load_process_state()
        self.assertEqual(process_state.current_stage, "candidate_rejected")
        self.assertEqual(process_state.current_step, "step_4")

        candidate_set = self.repository.load_candidate_experiments()
        self.assertTrue(candidate_set.rejected_candidates)
        self.assertGreaterEqual(rejected["remaining_candidates"], 0)

    def test_round_review_and_decision_are_logged(self) -> None:
        control = HumanControlService(self.repository, project_root=self.project_root)
        payload = control.request_round_review(
            round_id=1,
            experiment_id="E_R02_01",
            evaluation_summary={"pearson_r_delta": 0.05},
            hypothesis_assessments=[
                {
                    "hypothesis_id": "H1",
                    "support_before": 0.5,
                    "support_after": 0.58,
                    "status": "supported",
                    "direction_matched": True,
                    "magnitude_matched": "partial",
                    "reason": "test assessment context",
                }
            ],
            reasoning_traces=[
                {
                    "trace_id": "RT001",
                    "stage": "round_review_context",
                    "summary": "上一轮程序解释认为 H1 获得初步支持",
                    "related_hypotheses": ["H1"],
                    "related_uncertainties": ["U01"],
                    "support_delta": 0.08,
                }
            ],
        )
        self.assertEqual(payload["status"], "awaiting_round_decision")

        recorded = control.record_round_decision(
            round_id=1,
            decision="adjust",
            human_feedback="下一轮先测试 By 单变量路径",
        )
        self.assertEqual(recorded["status"], "recorded")

        decision_log = self.repository.load_decision_log()
        self.assertEqual(decision_log.decisions[-2].decision_type, "round_review_requested")
        self.assertEqual(decision_log.decisions[-1].decision_type, "round_adjusted")
        self.assertEqual(decision_log.human_feedback[-1].content, "下一轮先测试 By 单变量路径")
        self.assertEqual(decision_log.human_feedback[-1].linked_reasoning_trace_ids, ["RT001"])
        self.assertEqual(recorded["planning_status"], "awaiting_data_dictionary")

    def test_round_decision_adjust_rebuilds_candidate_plan(self) -> None:
        control = HumanControlService(self.repository, project_root=self.project_root)
        control.request_round_review(
            round_id=1,
            experiment_id="E_R02_01",
            evaluation_summary={"pearson_r_delta": 0.05},
            hypothesis_assessments=[
                {
                    "hypothesis_id": "H1",
                    "support_before": 0.5,
                    "support_after": 0.58,
                    "status": "supported",
                    "direction_matched": True,
                    "magnitude_matched": "partial",
                    "reason": "test assessment context",
                }
            ],
            disagreement_updates=[
                {
                    "uncertainty_id": "U01",
                    "compared_hypotheses": ["H1", "H2"],
                    "support_span_before": 0.20,
                    "support_span_after": 0.11,
                    "narrowed": True,
                    "resolution_status": "partially_resolved",
                    "leading_hypothesis_id": "H1",
                    "unresolved_hypotheses": ["H1", "H2"],
                    "summary": "U01 分歧缩小但仍需下一轮验证",
                }
            ],
            reasoning_traces=[
                {
                    "trace_id": "RT001",
                    "stage": "round_review_context",
                    "summary": "上一轮程序解释认为 H1 获得初步支持",
                    "related_hypotheses": ["H1"],
                    "related_uncertainties": ["U01"],
                    "support_delta": 0.08,
                }
            ],
        )

        recorded = control.record_round_decision(
            round_id=1,
            decision="adjust",
            human_feedback="下一轮先测试 By 单变量路径",
            data_dictionary=self.dictionary,
        )
        self.assertEqual(recorded["planning_status"], "candidate_plan_rebuilt")
        self.assertEqual(recorded["next_review"]["status"], "awaiting_human_review")
        self.assertEqual(recorded["planner_input"].next_round_id, 2)
        self.assertEqual(recorded["planner_input"].human_feedback, "下一轮先测试 By 单变量路径")
        self.assertTrue(recorded["planner_output"].candidate_supplements)
        self.assertTrue(recorded["planner_output"].protocol_refinements)
        self.assertGreaterEqual(recorded["applied_output"]["hypothesis_updates"], 1)
        self.assertGreaterEqual(recorded["applied_output"]["uncertainty_updates"], 1)

        candidate_set = self.repository.load_candidate_experiments()
        focused = [
            candidate
            for candidate in candidate_set.candidates
            if "human_feedback_focus_single_feature:By" in candidate.design.notes
        ]
        self.assertTrue(focused)
        self.assertEqual(focused[0].design.treatment, ["By"])

        planner_input = self.repository.load_planner_input()
        self.assertEqual(planner_input.source_round_id, 1)
        self.assertTrue(planner_input.unresolved_uncertainties)
        self.assertTrue(planner_input.recent_disagreement_updates)
        self.assertEqual(planner_input.recent_disagreement_updates[0].resolution_status, "partially_resolved")
        self.assertIn("human_feedback", planner_input.to_experiment_planner_payload())
        self.assertTrue(planner_input.to_central_controller_payload()["planner_guidance"])
        self.assertTrue(planner_input.recent_hypothesis_assessments)
        self.assertEqual(planner_input.recent_human_feedback[-1].linked_reasoning_trace_ids, ["RT001"])
        self.assertTrue(planner_input.recent_reasoning_traces)
        planner_output = self.repository.load_planner_output()
        self.assertTrue(planner_output.to_experiment_planner_payload()["candidate_supplements"])
        self.assertTrue(planner_output.to_scientific_interpreter_payload()["interpretation_enhancements"])

        process_state = self.repository.load_process_state()
        self.assertEqual(process_state.current_phase, "experiment_planning")
        self.assertEqual(process_state.current_stage, "awaiting_human_approval")

        tree = self.repository.load_hypothesis_tree()
        self.assertEqual(tree.latest_update.event, "planner_output_applied")
        self.assertTrue(tree.node_index()["H1"].critiques)
        self.assertEqual(tree.node_index()["H1"].critiques[-1].from_role, "scientific_interpreter")
        self.assertGreater(tree.node_index()["H1"].support_score, 0.6)
        self.assertEqual(tree.node_index()["H1"].support_history[-1].event, "planner_interpretation:IE001")

        uncertainties = self.repository.load_uncertainties()
        self.assertTrue(uncertainties.records[0].history)
        self.assertEqual(uncertainties.records[0].history[-1].event, "planner_interpretation")
        self.assertIsNotNone(uncertainties.records[0].notes)
        self.assertEqual(uncertainties.record_index()["U01"].priority, "high")
        self.assertEqual(uncertainties.record_index()["U02"].priority, "low")
        self.assertEqual(uncertainties.priority_queue.queue[0].uncertainty_id, "U01")

        experiment_memory = self.repository.load_experiment_memory()
        trace_entry = experiment_memory.entry_index()["E_R02_01"]
        self.assertTrue(trace_entry.reasoning_traces)
        self.assertEqual(trace_entry.reasoning_traces[-1].stage, "interpretation_enhancement")
        self.assertIsNotNone(trace_entry.reasoning_traces[-1].priority_delta)

        decision_log = self.repository.load_decision_log()
        self.assertEqual(decision_log.decisions[-4].decision_type, "planner_input_prepared")
        self.assertEqual(decision_log.decisions[-3].decision_type, "planner_output_generated")
        self.assertEqual(decision_log.decisions[-2].decision_type, "planner_output_applied")
        self.assertEqual(decision_log.decisions[-1].decision_type, "experiment_selection_requested")

    def test_round_decision_continue_rebuilds_candidate_plan_without_feedback(self) -> None:
        control = HumanControlService(self.repository, project_root=self.project_root)
        control.request_round_review(
            round_id=1,
            experiment_id="E_R02_01",
            evaluation_summary={"pearson_r_delta": 0.02},
        )

        recorded = control.record_round_decision(
            round_id=1,
            decision="continue",
            data_dictionary=self.dictionary,
        )
        self.assertEqual(recorded["planning_status"], "candidate_plan_rebuilt")
        self.assertEqual(recorded["next_review"]["status"], "awaiting_human_review")
        self.assertIsNone(recorded["planner_input"].human_feedback)

    def test_approve_candidate_consumes_planner_output_refinements(self) -> None:
        control = HumanControlService(self.repository, project_root=self.project_root)
        control.request_round_review(
            round_id=1,
            experiment_id="E_R02_01",
            evaluation_summary={"pearson_r_delta": -0.01, "stable": False},
        )
        control.record_round_decision(
            round_id=1,
            decision="adjust",
            human_feedback="下一轮先测试 By 单变量路径",
            data_dictionary=self.dictionary,
        )

        protocol = control.approve_candidate(auto_continue=False)
        self.assertIn("planner_refinement:feature_focus", protocol.notes)
        self.assertIn("planner_feedback_focus:By", protocol.notes)
        self.assertEqual(protocol.model.parameters["alpha"], 0.2)
        self.assertEqual(protocol.steps[0].action, "stability_validation")

    def test_request_pause_is_logged(self) -> None:
        control = HumanControlService(self.repository, project_root=self.project_root)
        control.request_stop(phase="experiment_execution", reason="先检查数据质量", pause=True)

        process_state = self.repository.load_process_state()
        self.assertTrue(process_state.user_requests.stop_requested)
        self.assertEqual(process_state.user_requests.stop_at_phase, "experiment_execution")

        decision_log = self.repository.load_decision_log()
        self.assertEqual(decision_log.stop_history[0].type, "pause")
        self.assertEqual(decision_log.decisions[0].decision_type, "pause_requested")

    def test_approve_execute_and_prepare_round_review(self) -> None:
        control = HumanControlService(self.repository, project_root=self.project_root, run_shap=False)
        control.request_experiment_selection_review()
        payload = control.approve_and_execute_candidate(
            human_notes="批准后直接执行",
            auto_continue=False,
        )

        self.assertEqual(payload["result"].status, "completed")
        self.assertEqual(payload["evaluation"].metrics.experiment_id, payload["protocol"].experiment_id)
        self.assertEqual(payload["review"]["status"], "awaiting_round_decision")
        self.assertTrue(payload["review"]["hypothesis_assessments"])
        self.assertTrue(payload["review"]["disagreement_updates"])
        self.assertTrue(payload["evaluation"].scientific.disagreement_updates)
        self.assertTrue(
            (self.project_root / "results" / f"round_{payload['protocol'].round_id:02d}" / "evaluation_unified.json").exists()
        )

        process_state = self.repository.load_process_state()
        self.assertEqual(process_state.current_stage, "awaiting_round_decision")
        self.assertEqual(process_state.current_phase, "decision_making")

        experiment_memory = self.repository.load_experiment_memory()
        self.assertEqual(experiment_memory.entries[0].experiment_id, payload["protocol"].experiment_id)

        uncertainties = self.repository.load_uncertainties()
        self.assertTrue(uncertainties.record_index()["U01"].history)
        self.assertIn(
            "disagreement_evaluation",
            [entry.event for entry in uncertainties.record_index()["U01"].history],
        )
        self.assertEqual(uncertainties.record_index()["U01"].resolving_experiment, payload["protocol"].experiment_id)
        self.assertIsNotNone(uncertainties.record_index()["U01"].notes)

        decision_log = self.repository.load_decision_log()
        self.assertEqual(decision_log.decisions[-1].decision_type, "round_review_requested")


if __name__ == "__main__":
    unittest.main()
