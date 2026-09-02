#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最小闭环主程序。
完全不修改原有代码，在外部包装AI调度层。
"""

from pathlib import Path

from core.schema import ExperimentConfig
from core.harness import ExperimentHarness
from core.round_manager import RoundManager
from llm.qwen_model import generate_next_plan


def main():
    print("\n" + "=" * 60)
    print("AI Scientist 最小闭环 — 太阳风速度预测")
    print("=" * 60)

    # ==================== 配置路径 ====================
    # 原代码的输入输出路径
    JSON_TEMPLATE = Path("config/experiment_config.json")
    JSON_OUTPUT = Path("config/round-config.json")
    RUNNER_SCRIPT = Path("models/elasticnet_runner.py")
    METRICS_OUTPUT = Path("outputs/elasticnet_metrics.json")

    # ==================== 初始化 ====================
    harness = ExperimentHarness(
        json_template_path=JSON_TEMPLATE,
        json_output_path=JSON_OUTPUT,
        runner_script_path=RUNNER_SCRIPT,
        metrics_output_path=METRICS_OUTPUT
    )

    manager = RoundManager()

    # ==================== Round 1: 基线 ====================
    round1_config = ExperimentConfig(
        window_size=3,
        use_lag_feature=False,
        max_lag_day=3,
        alpha=1,
        l1_ratio=0.5,
        reasoning="基线实验，使用原始配置"
    )

    result1 = harness.run_round(1, round1_config)
    manager.save_round(result1)

    print(manager.get_summary())

    # ==================== Qwen 生成 Round 2 ====================
    print(f"\n{'='*50}")
    print("Qwen 分析结果并生成下一轮计划")
    print(f"{'='*50}")

    plan_text = generate_next_plan(result1)

    # ==================== 校验Qwen输出 ====================
    try:
        round2_config = ExperimentConfig.model_validate_json(plan_text)
        print("\n✅ Pydantic校验通过!")
        print(f"   window_size: {round2_config.window_size}")
        print(f"   use_lag_feature: {round2_config.use_lag_feature}")
        print(f"   max_lag_day: {round2_config.max_lag_day}")
        print(f"   alpha: {round2_config.alpha}")
        print(f"   l1_ratio: {round2_config.l1_ratio}")
        print(f"   理由: {round2_config.reasoning}")
    except Exception as e:
        print(f"\n❌ Pydantic校验失败: {e}")
        print("请检查Qwen输出是否为合法JSON")
        return

    # ==================== Round 2: Qwen建议 ====================
    result2 = harness.run_round(2, round2_config)
    manager.save_round(result2)

    # ==================== 对比总结 ====================
    print("\n" + "=" * 60)
    print("闭环完成！两轮实验对比")
    print("=" * 60)

    m1 = result1["metrics"]
    m2 = result2["metrics"]

    print(f"""
┌─────────────────────┬──────────────┬──────────────┬─────────────┐
│ 指标                │ Round 1      │ Round 2      │ 变化        │
├─────────────────────┼──────────────┼──────────────┼─────────────┤
│ window_size         │ {result1['config']['window_size']:>12} │ {result2['config']['window_size']:>12} │             │
│ use_lag_feature     │ {str(result1['config']['use_lag_feature']):>12} │ {str(result2['config']['use_lag_feature']):>12} │             │
│ max_lag_day         │ {result1['config']['max_lag_day']:>12} │ {result2['config']['max_lag_day']:>12} │             │
├─────────────────────┼──────────────┼──────────────┼─────────────┤
│ Test RMSE           │ {m1.get('test_rmse', 0):>12.3f} │ {m2.get('test_rmse', 0):>12.3f} │ {m2.get('test_rmse', 0) - m1.get('test_rmse', 0):>+11.3f} │
│ Test R²             │ {m1.get('test_r2', 0):>12.3f} │ {m2.get('test_r2', 0):>12.3f} │ {m2.get('test_r2', 0) - m1.get('test_r2', 0):>+11.3f} │
│ Pearson r           │ {m1.get('test_pearson_r', 0):>12.3f} │ {m2.get('test_pearson_r', 0):>12.3f} │ {m2.get('test_pearson_r', 0) - m1.get('test_pearson_r', 0):>+11.3f} │
│ Baseline RMSE       │ {m1.get('baseline_test_rmse', 0):>12.3f} │ {m2.get('baseline_test_rmse', 0):>12.3f} │             │
└─────────────────────┴──────────────┴──────────────┴─────────────┘
""")

    if m2.get('test_r2', -999) > m1.get('test_r2', -999):
        print("\n✅ Round 2 的 R² 提升了！闭环迭代有效。")
    else:
        print("\n⚠️  Round 2 的 R² 未提升，可能需要继续迭代调整其他参数。")

    print("\n所有结果已保存至 results/ 目录")


if __name__ == "__main__":
    main()
