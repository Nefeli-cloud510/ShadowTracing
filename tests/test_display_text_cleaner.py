import unittest

from core.display_text_cleaner import (
    clean_llm_text,
    deep_clean_preserving_ids,
)


class DisplayTextCleanerTest(unittest.TestCase):
    def test_replaces_internal_hypothesis_and_status_tokens(self) -> None:
        cleaned = clean_llm_text(
            "H_shadow_incremental_gain 预期效应为 positive；"
            "direction_matched=True, magnitude_matched=False；status=weakened"
        )
        self.assertNotIn("H_shadow_incremental_gain", cleaned)
        self.assertNotIn("positive", cleaned)
        self.assertIn("相关假设", cleaned)
        self.assertIn("正向增强", cleaned)
        self.assertIn("方向匹配=一致", cleaned)
        self.assertIn("幅度匹配=不一致", cleaned)
        self.assertIn("已削弱", cleaned)

    def test_replaces_leading_span_and_narrowed_summary(self) -> None:
        cleaned = clean_llm_text(
            "leading hypothesis为H_shadow_incremental_gain，但narrowed=false"
        )
        self.assertIn("前沿假设为相关假设", cleaned)
        self.assertIn("支持度跨度未收窄", cleaned)
        self.assertNotIn("narrowed", cleaned)

    def test_replaces_note_prefixes_and_llm_draft_marks(self) -> None:
        cleaned = clean_llm_text(
            "hypothesis_triggers:llm_hypothesis_H1、llm_hypothesis_H2，resolved"
        )
        self.assertIn("假设触发来源：", cleaned)
        self.assertIn("H1（LLM 起草）", cleaned)
        self.assertIn("H2（LLM 起草）", cleaned)
        self.assertIn("已解决", cleaned)

    def test_replaces_metric_and_formula_tokens(self) -> None:
        cleaned = clean_llm_text(
            "按 IG_pair(H_i,H_j)=1-overlap、IG(E)=avg(IG_pair) 计算；"
            "预测区间来自 LLM 输出（metric=Pearson_r）"
        )
        self.assertNotIn("H_i", cleaned)
        self.assertNotIn("H_j", cleaned)
        self.assertIn("假设甲", cleaned)
        self.assertIn("假设乙", cleaned)
        self.assertIn("两两区分度", cleaned)
        self.assertIn("实验整体区分度", cleaned)
        self.assertIn("指标=皮尔逊相关系数", cleaned)
        self.assertNotIn("metric=", cleaned)

    def test_deep_clean_preserving_ids_keeps_structured_mapping(self) -> None:
        payload = {
            "hypothesis_id": "H_shadow_incremental_gain",
            "summary": "H_shadow_incremental_gain 已获得支持",
        }
        cleaned = deep_clean_preserving_ids(payload)
        self.assertEqual(cleaned["hypothesis_id"], "H_shadow_incremental_gain")
        self.assertNotIn("H_shadow_incremental_gain", cleaned["summary"])
        self.assertIn("获得支持", cleaned["summary"])


if __name__ == "__main__":
    unittest.main()
