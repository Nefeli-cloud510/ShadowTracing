import unittest

from core.rag_service import RAGContextBundle
from core.scientific_questioner_llm import ScientificQuestionerLLM
from core.unified_schema import (
    DataDictionarySummary,
    HypothesisSnapshot,
    PlannerEvaluationSummary,
    ReasoningPlannerInput,
)


class QuestionerMultiSourceFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.planner_input = ReasoningPlannerInput(
            task_id="ST_FALLBACK",
            source_round_id=1,
            next_round_id=2,
            scientific_question="竞争假设是否能被对照实验区分",
            target="Vsw",
            evaluation_summary=PlannerEvaluationSummary(
                round_id=1,
                delta_rmse=0.12,
                delta_pearson_r=-0.03,
                stable=False,
            ),
            active_hypotheses=[
                HypothesisSnapshot(
                    hypothesis_id="H1",
                    statement="By 对 Vsw 存在独立预测增益",
                    status="active",
                    support_score=0.62,
                )
            ],
            data_dictionary_summary=DataDictionarySummary(
                dictionary_id="DICT_FALLBACK",
                dataset_name="demo",
                time_column="TIME",
                target_candidates=["Vsw"],
                feature_candidates=["By", "Bz", "Np", "DeltaDec"],
            ),
        )
        self.rag_context = RAGContextBundle(query="multi source uncertainty")
        self.mined_candidates = [
            {
                "question": "H1 与 H2 的分歧是否能在 By 上通过对照实验直接区分？",
                "description": "两个竞争假设支持度接近，需要区分解释差异。",
                "priority": "high",
                "source_labels": ["from_hypothesis_conflict"],
                "related_hypotheses": ["H1", "H2"],
                "features": ["By", "Vsw"],
            },
            {
                "question": "By 模型的剩余误差是否仍集中出现在特定时段或极端事件？",
                "description": "上一轮残差存在结构化模式。",
                "priority": "medium",
                "source_labels": ["from_residual_pattern"],
                "related_hypotheses": ["H1"],
                "features": ["By", "Vsw"],
            },
            {
                "question": "H1 支持度下降是否受 Bz 的窗口选择驱动？",
                "description": "上一轮支持度发生较大移动，需要稳健性验证。",
                "priority": "high",
                "source_labels": ["from_support_shift"],
                "related_hypotheses": ["H1", "H2"],
                "features": ["Bz", "Vsw"],
            },
            {
                "question": "上一轮执行失败是否暴露出 Np 相关的数据或协议缺口？",
                "description": "失败归因记录提示应从协议收口后再执行。",
                "priority": "high",
                "source_labels": ["from_failed_execution"],
                "related_hypotheses": ["H1"],
                "features": ["Np", "Vsw"],
            },
        ]

    def test_fallback_consumes_mined_candidates_with_lineage(self) -> None:
        response = ScientificQuestionerLLM._fallback(
            self.planner_input,
            self.rag_context,
            self.mined_candidates,
        )

        self.assertGreaterEqual(len(response.proposed_uncertainties), 4)
        mined_question = self.mined_candidates[0]["question"]
        mined_records = [
            item
            for item in response.proposed_uncertainties
            if item.question == mined_question
        ]
        self.assertEqual(len(mined_records), 1)
        self.assertIn("from_hypothesis_conflict", mined_records[0].mining_sources)
        self.assertEqual(mined_records[0].related_hypotheses, ["H1", "H2"])
        self.assertEqual(mined_records[0].features, ["By", "Vsw"])

        source_labels = {
            label
            for item in response.proposed_uncertainties
            for label in item.mining_sources
        }
        self.assertTrue(
            {
                "from_hypothesis_conflict",
                "from_residual_pattern",
                "from_support_shift",
                "from_failed_execution",
            }.issubset(source_labels)
        )


if __name__ == "__main__":
    unittest.main()
