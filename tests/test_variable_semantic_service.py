import unittest
from datetime import datetime

from core.unified_schema import DataDictionary, DataDictionarySummary, FieldDescriptor
from core.variable_semantic_service import VariableSemanticService


class VariableSemanticServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dictionary = DataDictionary(
            dictionary_id="DICT_SEMANTIC_001",
            generated_at=datetime.now(),
            version="1.0",
            dataset_name="demo",
            total_samples=100,
            time_column="TIME",
            time_format="YYYYMMDD",
            fields=[
                FieldDescriptor(
                    field_name="SW Plasma Speed, km/s",
                    data_type="float64",
                    physical_meaning="太阳风速度",
                    display_name="太阳风速度",
                ),
                FieldDescriptor(
                    field_name="p2_y中心值",
                    data_type="float64",
                    physical_meaning="宇宙线日影南北偏移",
                    display_name="宇宙线日影南北偏移",
                ),
                FieldDescriptor(
                    field_name="BY, nT (GSE)",
                    data_type="float64",
                    physical_meaning="行星际磁场Y分量（GSE坐标）",
                    display_name="行星际磁场Y分量（GSE坐标）",
                ),
            ],
            target_candidates=["SW Plasma Speed, km/s"],
            feature_candidates=["p2_y中心值", "BY, nT (GSE)"],
        )
        self.service = VariableSemanticService.from_data_dictionary(self.dictionary)

    def test_display_names_replace_raw_headers_in_business_text(self) -> None:
        text = (
            "SW Plasma Speed, km/s 与 p2_y中心值 的关系是否需要 BY, nT (GSE) 作为中介？"
        )
        displayed = self.service.display_text(text)
        self.assertNotIn("SW Plasma Speed, km/s", displayed)
        self.assertNotIn("p2_y中心值", displayed)
        self.assertNotIn("BY, nT (GSE)", displayed)
        self.assertIn("太阳风速度", displayed)
        self.assertIn("宇宙线日影南北偏移", displayed)
        self.assertIn("行星际磁场Y分量（GSE坐标）", displayed)

    def test_display_text_preserves_stable_hypothesis_ids(self) -> None:
        text = (
            "H_p2_y中心值_branch_by_nt_gse 关于 SW Plasma Speed, km/s 与 BY, nT (GSE) 的解释"
            "是否仍受未建模条件约束？"
        )
        displayed = self.service.display_text(text)
        self.assertIn("H_p2_y中心值_branch_by_nt_gse", displayed)
        self.assertNotIn("H_宇宙线日影南北偏移_branch_by_nt_gse", displayed)
        self.assertNotIn("SW Plasma Speed, km/s", displayed)
        self.assertNotIn("BY, nT (GSE)", displayed)
        self.assertIn("太阳风速度", displayed)
        self.assertIn("行星际磁场Y分量（GSE坐标）", displayed)

    def test_display_raw_round_trip_is_stable(self) -> None:
        for raw in self.dictionary.target_candidates + self.dictionary.feature_candidates:
            self.assertEqual(self.service.to_raw(self.service.to_display(raw)), raw)
        self.assertEqual(
            self.service.display_list(self.dictionary.feature_candidates),
            ["宇宙线日影南北偏移", "行星际磁场Y分量（GSE坐标）"],
        )
        self.assertEqual(
            self.service.raw_list(
                ["宇宙线日影南北偏移", "行星际磁场Y分量（GSE坐标）"],
            ),
            self.dictionary.feature_candidates,
        )

    def test_build_display_summary_keeps_raw_execution_fields_intact(self) -> None:
        base_summary = DataDictionarySummary(
            dictionary_id="runtime",
            dataset_name="demo",
            time_column="TIME",
            target_candidates=self.dictionary.target_candidates,
            feature_candidates=self.dictionary.feature_candidates,
        )
        display_summary = self.service.build_display_summary(base_summary)
        self.assertEqual(display_summary.time_column, "TIME")
        self.assertEqual(display_summary.target_candidates, self.dictionary.target_candidates)
        self.assertEqual(display_summary.feature_candidates, self.dictionary.feature_candidates)
        self.assertEqual(display_summary.display_target_candidates, ["太阳风速度"])
        self.assertEqual(display_summary.display_feature_candidates, ["宇宙线日影南北偏移", "行星际磁场Y分量（GSE坐标）"])
        self.assertEqual(
            display_summary.raw_display_map["BY, nT (GSE)"],
            "行星际磁场Y分量（GSE坐标）",
        )
        self.assertEqual(
            display_summary.display_raw_map["太阳风速度"],
            "SW Plasma Speed, km/s",
        )


if __name__ == "__main__":
    unittest.main()
