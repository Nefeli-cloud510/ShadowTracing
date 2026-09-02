import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.evaluation_unified import evaluate_experiment
from core.harness_unified import UnifiedExperimentHarness
from core.protocol_bridge import (
    ElasticNetDataSourceConfig,
    ElasticNetProtocolBridge,
    legacy_config_to_protocol,
)
from core.schema import ExperimentConfig as LegacyExperimentConfig
from core.unified_schema import ExperimentProtocol, ModelSpec


class UnifiedExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "config").mkdir()
        (self.root / "outputs").mkdir()
        (self.root / "results").mkdir()

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

        self.omni_path = self.root / "omni.csv"
        self.lhaaso_path = self.root / "lhaaso.csv"
        omni.to_csv(self.omni_path, index=False)
        lhaaso.to_csv(self.lhaaso_path, index=False)

        self.data_source = ElasticNetDataSourceConfig(
            omni_file_path=self.omni_path,
            lhaaso_file_path=self.lhaaso_path,
            time_column="TIME",
            target_column="Vsw",
            test_split_ratio=0.25,
            random_state=7,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_bridge_builds_runner_config(self) -> None:
        protocol = ExperimentProtocol(
            experiment_id="E01",
            round_id=1,
            task_id="ST_001",
            target="Vsw",
            features={
                "target": "Vsw",
                "control": ["By", "Bz"],
                "treatment": ["By", "Bz", "DeltaDec"],
                "lags": {"DeltaDec": [1, 2]},
            },
            model=ModelSpec(
                name="ElasticNet",
                parameters={
                    "window_size": 3,
                    "use_lag_feature": True,
                    "max_lag_day": 2,
                    "alpha": 0.2,
                    "l1_ratio": 0.6,
                    "random_state": 7,
                    "test_split_ratio": 0.25,
                },
            ),
        )
        bridge = ElasticNetProtocolBridge(self.data_source)
        config = bridge.build_runner_config(protocol, ["By", "Bz", "DeltaDec"])

        self.assertEqual(config.file_config.target_column, "Vsw")
        self.assertEqual(config.time_window_config.window_size, 3)
        self.assertAlmostEqual(config.elasticnet_config.alpha, 0.2)

    def test_legacy_adapter(self) -> None:
        legacy = LegacyExperimentConfig(
            window_size=5,
            use_lag_feature=True,
            max_lag_day=2,
            alpha=0.25,
            l1_ratio=0.65,
            reasoning="legacy config",
        )
        protocol = legacy_config_to_protocol(
            legacy,
            round_id=2,
            task_id="ST_002",
            target="Vsw",
            control_features=["By", "Bz"],
            treatment_features=["By", "Bz", "DeltaDec"],
            experiment_id="E02",
        )

        self.assertEqual(protocol.model.parameters["window_size"], 5)
        self.assertEqual(protocol.features.treatment[-1], "DeltaDec")

    def test_unified_harness_runs_real_runner(self) -> None:
        protocol = ExperimentProtocol(
            experiment_id="E03",
            round_id=1,
            task_id="ST_003",
            target="Vsw",
            features={
                "target": "Vsw",
                "control": ["By", "Bz"],
                "treatment": ["By", "Bz", "DeltaDec"],
                "lags": {"DeltaDec": [1, 2]},
            },
            model=ModelSpec(
                name="ElasticNet",
                parameters={
                    "window_size": 4,
                    "use_lag_feature": True,
                    "max_lag_day": 2,
                    "alpha": 0.1,
                    "l1_ratio": 0.5,
                    "random_state": 7,
                    "test_split_ratio": 0.25,
                },
            ),
        )
        harness = UnifiedExperimentHarness(
            data_source=self.data_source,
            project_root=self.root,
            run_shap=False,
        )
        result = harness.run(protocol)
        evaluation = evaluate_experiment(
            result,
            protocol=protocol,
            remaining_uncertainties=[{"question": "DeltaDec 的增益是否跨时间段稳定"}],
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.runs), 2)
        self.assertTrue((self.root / "results" / "round_01" / "result_unified.json").exists())
        self.assertTrue((self.root / "config" / "latest_protocol.json").exists())
        self.assertTrue((self.root / "outputs" / "latest_metrics.json").exists())
        self.assertFalse(Path(result.runs[0].prediction_artifact).is_absolute())
        self.assertTrue(result.visualizations)
        self.assertFalse(Path(result.visualizations[0].path).is_absolute())
        self.assertEqual(evaluation.metrics.experiment_id, "E03")
        self.assertIsNotNone(evaluation.metrics.pg_actual_signed)
        self.assertGreaterEqual(evaluation.metrics.pg_actual_clipped, 0.0)
        self.assertEqual(
            evaluation.scientific.evidence_summary.remaining_uncertainties[0]["question"],
            "DeltaDec 的增益是否跨时间段稳定",
        )
        self.assertEqual(evaluation.visualizations[0].path, result.visualizations[0].path)


if __name__ == "__main__":
    unittest.main()
