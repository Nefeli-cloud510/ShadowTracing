import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.decision_unified import (
    CandidateExperimentGenerator,
    DecisionLayerService,
    UncertaintyPrioritizer,
    UtilityScorer,
)
from core.state_repository import UnifiedStateRepository
from core.unified_schema import (
    DataDictionary,
    EvaluationSpec,
    ExperimentMemoryEntry,
    FieldDescriptor,
    HypothesisNode,
    MetricDelta,
    PerformanceMetrics,
    ResearchQuestion,
    ScientificConstraints,
    ScientificTask,
    ScientificTaskPayload,
    UncertaintyRecord,
    VariableBinding,
)


class DecisionLayerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.repository = UnifiedStateRepository(self.project_root)

        self.task = ScientificTask(
            task_id="ST_200",
            payload=ScientificTaskPayload(
                research_question=ResearchQuestion(
                    text="DeltaDec 是否能改善 Vsw 预测",
                    target="Vsw",
                    question_type="forecasting",
                    variables=VariableBinding(
                        x="DeltaDec",
                        y="Vsw",
                        m_candidates=["By", "Bz"],
                    ),
                ),
                evaluation=EvaluationSpec(primary_metric="RMSE", secondary_metrics=["Pearson_r"]),
                constraints=ScientificConstraints(),
            ),
        )
        self.dictionary = DataDictionary(
            dictionary_id="DICT_200",
            generated_at=datetime.now(),
            version="1.0",
            dataset_name="demo",
            total_samples=100,
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
                    support_score=0.65,
                    activation_condition="always",
                ),
                HypothesisNode(
                    hypothesis_id="H2",
                    statement="DeltaDec 主要通过 By 起作用",
                    level=1,
                    status="active",
                    support_score=0.35,
                    activation_condition="always",
                ),
            ],
            initial_uncertainties=[
                UncertaintyRecord(
                    uncertainty_id="U01",
                    question="DeltaDec 是否具有独立增量信息？",
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
                    description="需要检验滞后与稳定性。",
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

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_prioritize_generate_and_score(self) -> None:
        tree = self.repository.load_hypothesis_tree()
        uncertainties = self.repository.load_uncertainties()

        prioritized = UncertaintyPrioritizer().prioritize(uncertainties, tree)
        self.assertEqual(prioritized.queue[0].uncertainty_id, "U01")
        self.assertGreater(prioritized.queue[0].priority_score, prioritized.queue[1].priority_score)
        self.assertIn("H1", uncertainties.record_index()["U01"].disagreement)
        self.assertAlmostEqual(uncertainties.record_index()["U01"].disagreement["H1"].support_score, 0.65)

        candidates = CandidateExperimentGenerator().generate(
            task=self.task,
            data_dictionary=self.dictionary,
            hypothesis_tree=tree,
            uncertainty_state=uncertainties,
        )
        scored = UtilityScorer().score(candidates)

        self.assertTrue(scored.candidates)
        self.assertEqual(scored.candidates[0].design.target, "Vsw")
        self.assertIn("DeltaDec", scored.candidates[0].design.treatment)
        self.assertIsNotNone(scored.candidates[0].utility_score)
        review_candidates = [candidate for candidate in scored.candidates if candidate.requires_human_review]
        self.assertTrue(any("disagreement_hypotheses" in note for note in review_candidates[0].design.notes))

    def test_service_saves_candidate_plan(self) -> None:
        service = DecisionLayerService(self.repository)
        plan = service.build_candidate_plan(task=self.task, data_dictionary=self.dictionary)

        self.assertTrue(plan.candidates)
        self.assertTrue((self.project_root / "state" / "candidate_experiments.json").exists())
        self.assertIsNotNone(plan.top_candidate())
        self.assertGreaterEqual(plan.top_candidate().utility_score, plan.candidates[-1].utility_score)

    def test_generated_hypothesis_rationale_flows_into_candidate_design(self) -> None:
        repository = UnifiedStateRepository(self.project_root / "generated")
        repository.initialize_state_skeleton(
            self.task,
            initial_uncertainties=[
                UncertaintyRecord(
                    uncertainty_id="U10",
                    question="DeltaDec 的贡献是否独立于 By？",
                    description="需要区分独立增量与中介解释。",
                    related_hypotheses=[],
                    status="active",
                    priority="high",
                    created_at_round=0,
                    created_by="tester",
                )
            ],
            data_dictionary=self.dictionary,
            overwrite=True,
        )
        service = DecisionLayerService(repository)
        plan = service.build_candidate_plan(task=self.task, data_dictionary=self.dictionary)

        review_candidates = [candidate for candidate in plan.candidates if candidate.requires_human_review]
        self.assertTrue(review_candidates)
        self.assertTrue(any("hypothesis_triggers:" in note for note in review_candidates[0].design.notes))
        self.assertIn("区分这些假设来源", review_candidates[0].distinguishing_insight)

    def test_service_injects_human_feedback_into_next_round_candidates(self) -> None:
        service = DecisionLayerService(self.repository)
        plan = service.build_candidate_plan(
            task=self.task,
            data_dictionary=self.dictionary,
            planning_feedback="下一轮先测试 By 单变量路径",
        )

        focused = [
            candidate for candidate in plan.candidates if "human_feedback:下一轮先测试 By 单变量路径" in candidate.design.notes
        ]
        self.assertTrue(focused)
        review_candidates = [candidate for candidate in focused if candidate.requires_human_review]
        self.assertTrue(review_candidates)
        self.assertEqual(review_candidates[0].design.treatment, ["By"])
        self.assertIn("human_feedback_focus_single_feature:By", review_candidates[0].design.notes)
        self.assertIn("human_feedback", plan.note)

    def test_partially_resolved_uncertainty_turns_into_validation_followup(self) -> None:
        tree = self.repository.load_hypothesis_tree()
        uncertainties = self.repository.load_uncertainties()
        uncertainties.record_index()["U01"].resolution_status = "partially_resolved"
        uncertainties.record_index()["U01"].priority = "medium"
        self.repository.save_uncertainties(uncertainties)

        prioritized = UncertaintyPrioritizer().prioritize(uncertainties, tree)
        service = DecisionLayerService(self.repository)
        plan = service.build_candidate_plan(task=self.task, data_dictionary=self.dictionary)

        candidate = next(
            item
            for item in plan.candidates
            if item.requires_human_review and "U01" in item.related_uncertainties
        )
        self.assertEqual(candidate.type, "validation_followup")
        self.assertIn("validation_followup_for_partially_resolved_disagreement", candidate.design.notes)
        self.assertLess(prioritized.queue[0].priority_score, 0.85)

    def test_expected_performance_gain_uses_history_based_rmse_formula(self) -> None:
        experiment_memory = self.repository.load_experiment_memory()
        experiment_memory.entries.append(
            ExperimentMemoryEntry(
                experiment_id="E_HIST_01",
                round_id=1,
                status="completed",
                tested_hypotheses=["H1"],
                metrics_snapshot=PerformanceMetrics(
                    experiment_id="E_HIST_01",
                    round_id=1,
                    baseline_rmse=12.0,
                    treatment_rmse=11.0,
                    delta=MetricDelta(rmse=-1.0, pearson_r=0.04),
                ),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        self.repository.save_experiment_memory(experiment_memory)

        tree = self.repository.load_hypothesis_tree()
        uncertainties = self.repository.load_uncertainties()
        candidates = CandidateExperimentGenerator().generate(
            task=self.task,
            data_dictionary=self.dictionary,
            hypothesis_tree=tree,
            uncertainty_state=uncertainties,
            experiment_memory=experiment_memory,
        )

        formula_candidates = [
            candidate
            for candidate in candidates.candidates
            if candidate.estimated_performance_gain
            and candidate.estimated_performance_gain.rationale
            and "PG_expected(E)" in candidate.estimated_performance_gain.rationale
        ]
        self.assertTrue(formula_candidates)
        positive_gain_candidates = [
            candidate for candidate in formula_candidates if candidate.estimated_performance_gain.value > 0.0
        ]
        self.assertTrue(positive_gain_candidates)
        self.assertIn("PG_expected(E)", positive_gain_candidates[0].estimated_performance_gain.rationale)


if __name__ == "__main__":
    unittest.main()
