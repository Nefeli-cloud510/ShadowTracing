import unittest
from datetime import datetime

from core.decision_unified import (
    _estimate_llm_cost_yuan,
    _estimate_llm_token_usage,
    _formal_cost_score,
    _formal_risk_score,
)
from core.runtime_config import get_bailian_model_prices
from core.unified_schema import (
    CandidateExperiment,
    DataDictionary,
    EvaluationSpec,
    ExperimentDesign,
    FieldDescriptor,
    HypothesisNode,
    HypothesisTreeState,
    ResearchQuestion,
    ResourceBudget,
    ScientificConstraints,
    ScientificTask,
    ScientificTaskPayload,
    VariableBinding,
)


class CostPricingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.task = ScientificTask(
            task_id="ST_PRICE_01",
            payload=ScientificTaskPayload(
                research_question=ResearchQuestion(
                    text="DeltaDec 是否能改善 Vsw 预测",
                    target="Vsw",
                    question_type="forecasting",
                    variables=VariableBinding(x="DeltaDec", y="Vsw"),
                ),
                evaluation=EvaluationSpec(primary_metric="RMSE", secondary_metrics=["Pearson_r"]),
                constraints=ScientificConstraints(
                    resource_budget=ResourceBudget(token_budget=200000, max_time_seconds_per_round=300),
                ),
            ),
        )
        self.dictionary = DataDictionary(
            dictionary_id="DICT_PRICE_01",
            generated_at=datetime.now(),
            version="1.0",
            dataset_name="demo",
            total_samples=1000,
            time_column="TIME",
            time_format="YYYYMMDD",
            fields=[
                FieldDescriptor(field_name="TIME", data_type="int", physical_meaning="time"),
                FieldDescriptor(field_name="Vsw", data_type="float", physical_meaning="target"),
                FieldDescriptor(field_name="By", data_type="float", physical_meaning="IMF By"),
                FieldDescriptor(field_name="DeltaDec", data_type="float", physical_meaning="LHAASO DeltaDec"),
            ],
            target_candidates=["Vsw"],
            feature_candidates=["By", "DeltaDec"],
        )
        self.tree = HypothesisTreeState(
            tree_id="TREE_PRICE_01",
            task_id=self.task.task_id,
            root_question="DeltaDec 是否能改善 Vsw 预测",
            nodes=[
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
            active_hypotheses=["H1", "H2"],
        )
        self.candidate = CandidateExperiment(
            experiment_id="E_R01_01",
            type="distinguishing",
            purpose="检验 DeltaDec 是否带来独立预测信息",
            tested_hypotheses=["H1", "H2"],
            design=ExperimentDesign(
                target="Vsw",
                control=["By"],
                treatment=["By", "DeltaDec"],
                lags={"By": [1, 3], "DeltaDec": [1, 3]},
                design_focus="DeltaDec",
            ),
            requires_human_review=True,
        )

    def test_flash_and_max_prices_match_user_table(self) -> None:
        flash = get_bailian_model_prices("Qwen3.8-Flash")
        self.assertEqual(flash["input"], 0.80)
        self.assertEqual(flash["output"], 2.70)
        maximum = get_bailian_model_prices("qwen3.8-max")
        self.assertEqual(maximum["input"], 12.00)
        self.assertEqual(maximum["output"], 36.00)
        self.assertEqual(maximum["input_cached"], 1.50)

    def test_token_usage_and_fee_use_split_rates(self) -> None:
        input_tokens, output_tokens = _estimate_llm_token_usage(
            candidate=self.candidate,
            hypothesis_tree=self.tree,
            experiment_memory=None,
        )
        fee = _estimate_llm_cost_yuan(
            candidate=self.candidate,
            hypothesis_tree=self.tree,
            experiment_memory=None,
            price_rates={"input": 0.80, "output": 2.70},
        )
        expected_fee = (input_tokens * 0.80 + output_tokens * 2.70) / 1_000_000.0
        self.assertGreater(input_tokens, 0)
        self.assertGreater(output_tokens, 0)
        self.assertAlmostEqual(fee, expected_fee, places=8)

    def test_cost_rationale_includes_real_money_and_rates(self) -> None:
        cost, rationale = _formal_cost_score(
            candidate=self.candidate,
            task=self.task,
            data_dictionary=self.dictionary,
            hypothesis_tree=self.tree,
            experiment_memory=None,
        )
        self.assertGreater(cost, 0.0)
        self.assertLessEqual(cost, 1.0)
        self.assertIn("元/百万 tokens", rationale)
        self.assertIn("真实计费", rationale)
        self.assertIn("LLM真实费用占比", rationale)

    def test_risk_rationale_reports_dominant_dimension(self) -> None:
        risk, rationale = _formal_risk_score(
            candidate=self.candidate,
            task=self.task,
            data_dictionary=self.dictionary,
            hypothesis_tree=self.tree,
            experiment_memory=None,
        )
        self.assertGreaterEqual(risk, 0.0)
        self.assertLessEqual(risk, 1.0)
        self.assertIn("最高风险分项", rationale)


if __name__ == "__main__":
    unittest.main()
