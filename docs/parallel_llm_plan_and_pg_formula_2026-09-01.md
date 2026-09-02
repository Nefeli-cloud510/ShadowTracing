# 推理规划层并行多角色方案 + PG公式修正版

> 本方案在不重写 unified 主链、不移除 PI 审批节点的前提下，对推理规划层的 LLM 协作方式进行升级：
> 由“串行单模型多角色”调整为“分角色选模型 + 局部并行”。
> 同时补全选择决策层中的性能增益 `PG(E)` 定义，区分“实验前预测 PG”与“实验后实际 PG”。

---

## 一、修改目标

### 1.1 当前问题

当前系统已经具备：

- `CentralController`、`HypothesisProposer`、`ScientificQuestioner`、`ExperimentPlanner`、`ScientificInterpreter` 五个角色的结构化调用链
- `planner_input -> candidate_experiments -> PI审批 -> protocol -> execution -> evaluation -> planner_output` 的 unified 主链
- 真实 API 环境下两轮完整闭环的基础能力

但当前真实 API 运行暴露出两个现实问题：

1. 五个角色若全部串行调用高质量慢模型，整体响应时间过长，正式演示体验差
2. 目前 `PG(E)` 的文档与代码实现仍以启发式估计为主，尚未完整固化为“实验前预测 + 实验后审计”的双轨公式


### 1.2 本次调整目标

本次只做以下两类调整：

1. **LLM 调度层升级**
   - `HypothesisProposer` 与 `ScientificQuestioner` 改为并行调用
   - 按角色分配不同模型

2. **性能增益公式补全**
   - 统一 `PG_expected(E)` 与 `PG_actual(E)` 的定义
   - 明确第一轮、第二轮及以后在综合价值公式中的使用方式


### 1.3 不改动范围

- 不重写 `core/control_unified.py` 主流程
- 不移除 `HumanControlService` 中的 PI 审批节点
- 不把数值计算交回给 LLM
- 不改变状态文件主结构：`hypothesis_tree.json`、`uncertainties.json`、`experiment_memory.json`、`planner_input.json`、`planner_output.json`

---

## 二、角色协作新方案

### 2.1 最终采用方案

本次采用以下角色-模型映射：

| 角色 | 主要职责 | 调用方式 | 模型 |
|---|---|---|---|
| `HypothesisProposer` | 生成下一轮假设扩展与特征聚焦建议 | **并行** | `qwen-plus` |
| `ScientificQuestioner` | 生成批判点、不确定性与区分条件建议 | **并行** | `qwen-plus` |
| `CentralController` | 汇总并仲裁候选实验补充、解释增强与协议细化 | 串行 | `qwen3.8-max` |
| `ExperimentPlanner` | 生成协议补充、参数建议、额外实验步骤 | 串行 | `qwen-plus` |
| `ScientificInterpreter` | 生成结果解释增强与假设影响建议 | 串行 | `qwen3.8-max` |


### 2.2 核心思想

并不是把“一个慢模型扮演五个角色”完全替换成“多个 agent 自由对话”，而是：

- 把**可天然并行**的角色并行化
- 把**需要高质量裁决**的角色保留在高质量模型上
- 把**需要结构化但相对模板化**的角色放到更快模型上

这样做的目的不是追求“多 agent 炫技”，而是同时满足：

- 真实闭环能跑通
- 响应时间可接受
- 科学解释质量不明显下降
- 审计链仍清楚可追溯

---

## 三、并行边界设计

### 3.1 可以并行的环节

以下两个角色共享同一份输入，可直接并行：

- `HypothesisProposer`
- `ScientificQuestioner`

二者共同输入：

- `planner_input`
- `RAGContextBundle`
- 当前 `hypothesis_tree`
- 当前 `uncertainties`
- 当前 round 的 `evaluation_summary`

它们输出的内容互补：

- `HypothesisProposer` 关注“下一轮应该围绕什么假设和什么特征继续展开”
- `ScientificQuestioner` 关注“当前哪些逻辑薄弱、哪些不确定性最关键、哪些区分条件最重要”

二者之间没有严格前后依赖，因此可以在中央控制器汇总前并行执行。


### 3.2 不应并行的环节

以下角色保留串行：

1. `CentralController`
   - 必须在收到 proposer/questioner 结果后做统一仲裁

2. `ExperimentPlanner`
   - 需要读取已经确定的 `candidate plan`、`focus ids`、`protocol_notes`

3. `ScientificInterpreter`
   - 必须等实验执行结果与评价结果都出来以后再运行


### 3.3 新的时序关系

```Plain Text
planner_input + rag_context
        │
        ├───────────────┬────────────────┐
        │               │                │
        ▼               ▼                │
HypothesisProposer   ScientificQuestioner│
   (qwen-plus)          (qwen-plus)      │
        └───────────────┴────────────────┘
                        │
                        ▼
               CentralController
                 (qwen3.8-max)
                        │
                        ▼
                ExperimentPlanner
                  (qwen-plus)
                        │
                PI审批 / Harness执行
                        │
                        ▼
              ScientificInterpreter
                (qwen3.8-max)
                        │
                        ▼
             planner_output_applier
```

---

## 四、模块落地方案

### 4.1 模块定位

| 维度 | 说明 |
|---|---|
| 模块名称 | 并行多角色 LLM 调度器 |
| 所在层级 | 推理规划层 |
| 目标 | 在不改 unified 主链的前提下，实现 proposer/questioner 并行，并支持按角色选模型 |
| 上游输入 | `planner_input`、`RAGContextBundle`、`candidate_plan`、`evaluation_summary` |
| 下游输出 | `planner_output` 补充建议、协议补充、解释增强 |


### 4.2 建议新增组件

建议新增一个轻量编排器，例如：

`core/parallel_reasoning_orchestrator.py`

只做两件事：

1. 并行调用 proposer 和 questioner
2. 将两者结果打包交给 `CentralController`

它不负责改写状态，也不直接落盘。


### 4.3 输入输出接口

#### 输入

```json
{
  "planner_input": "...",
  "rag_context": "...",
  "candidate_plan": "...",
  "model_routing": {
    "hypothesis_proposer": "qwen-plus",
    "scientific_questioner": "qwen-plus",
    "central_controller": "qwen3.8-max",
    "experiment_planner": "qwen-plus",
    "scientific_interpreter": "qwen3.8-max"
  }
}
```


#### 中间汇总输出

```json
{
  "parallel_reasoning_bundle": {
    "hypothesis_proposer": {
      "focus_features": ["DeltaDec", "By"],
      "guidance_notes": ["优先验证独立增量是否仍存在"]
    },
    "scientific_questioner": {
      "challenge_points": ["By中介解释仍未排除"],
      "proposed_uncertainties": [
        {
          "question": "控制By后DeltaDec是否仍具独立增量？",
          "priority": "high"
        }
      ]
    }
  }
}
```


### 4.4 与中央控制器的对接

中央控制器读取并行 bundle 后，继续输出：

- `candidate_focus_ids`
- `candidate_rationale`
- `target_hypothesis_id`
- `related_uncertainty_ids`
- `feature_focus`
- `protocol_notes`
- `suggested_model_parameters`

程序仍由 `PlannerOutputBuilder` 和 `PlannerOutputApplier` 负责落盘，不改变当前写回链。

---

## 五、建议代码调整顺序

### 5.1 第一阶段：先做配置层

先增加角色模型配置，不碰主逻辑：

```yaml
llm_role_models:
  hypothesis_proposer: qwen-plus
  scientific_questioner: qwen-plus
  central_controller: qwen3.8-max
  experiment_planner: qwen-plus
  scientific_interpreter: qwen3.8-max
```

并支持在 `runtime_config.py` 中读取。


### 5.2 第二阶段：新增并行编排器

新增轻量 orchestrator：

- 输入 `planner_input + rag_context`
- 使用线程池或异步任务
- 并发执行 proposer/questioner
- 收集结果后返回 bundle


### 5.3 第三阶段：接入 PlannerOutputBuilder

把原先串行调用：

- proposer
- questioner

替换为：

- orchestrator.parallel_reason()

然后再把 bundle 交给 `CentralController`


### 5.4 第四阶段：演示脚本和真实 API 验活同步升级

正式验活脚本里也使用同一角色路由配置，避免“生产链和 demo 链不一致”。

---

## 六、审计与日志要求

### 6.1 必须新增的日志字段

建议在实验记忆或独立 telemetry 中补以下字段：

```json
{
  "llm_parallel_trace": {
    "round_id": 2,
    "parallel_group": "proposer_questioner",
    "started_at": "...",
    "finished_at": "...",
    "roles": {
      "hypothesis_proposer": {
        "model": "qwen-plus",
        "latency_seconds": 13.8,
        "fallback_used": false
      },
      "scientific_questioner": {
        "model": "qwen-plus",
        "latency_seconds": 34.2,
        "fallback_used": false
      }
    }
  }
}
```


### 6.2 审计原则

- 并行只是执行方式变化，不改变每个角色“谁生成了什么”的责任归属
- 每个角色的输出仍保留独立记录
- 中央控制器的裁决必须明确写明“综合了 proposer/questioner 的哪些建议”
- PI 审批节点仍位于 protocol 执行前

---

## 七、性能增益 PG 公式检查与补全

### 7.1 当前文档存在的问题

现有设计稿中，`PG(E)` 部分存在三个不够清晰的地方：

1. 把“实验前预测 PG”和“实验后实际 PG”混在了一起
2. 公式里同时出现 `RMSE_predicted(E)`、`RMSE_ideal`，但没有说清楚实际采用哪一个
3. 当前系统评价时同时看 `RMSE` 和 `Pearson_r`，但 PG 只写了 RMSE 版本，缺少统一解释


### 7.2 建议的总原则

性能增益应分成两类：

1. **实验前预测性能增益** `PG_expected(E)`
   - 用于候选实验综合价值打分
   - 是预测值，不是事实

2. **实验后实际性能增益** `PG_actual(E)`
   - 用于审计、留档和后续轮次学习
   - 是真实执行后的确定性结果


### 7.3 实验后实际性能增益：你给出的公式

你给出的图片公式是正确的，适合作为 **RMSE 型实际性能增益** 的主公式：

```Plain Text
PG_actual(E) = (RMSE_before - RMSE_after) / RMSE_before
```

其中：

- `RMSE_before`：本轮实验中 baseline/control 模型的 RMSE
- `RMSE_after`：本轮实验中 treatment 模型的 RMSE


### 7.4 需要补上的边界条件

为了能直接落地到程序，需要补充：

```Plain Text
PG_actual(E) = (RMSE_before - RMSE_after) / max(RMSE_before, ε)
```

其中：

- `ε` 是极小正数，建议取 `1e-8`
- 用于防止分母为 0


### 7.5 取值解释

该值是**有符号增益**：

- `PG_actual(E) > 0`：性能提升
- `PG_actual(E) = 0`：无提升
- `PG_actual(E) < 0`：性能下降

建议系统内部同时保留两个版本：

1. `pg_actual_signed`
2. `pg_actual_clipped`

定义如下：

```Plain Text
pg_actual_signed  = (RMSE_before - RMSE_after) / max(RMSE_before, ε)
pg_actual_clipped = clip(pg_actual_signed, 0, 1)
```

用途区分：

- `pg_actual_signed`：用于科研审计，允许显示“做差了”
- `pg_actual_clipped`：用于后续归一化汇总、前端进度条和 utility 学习特征


### 7.6 实验前预测性能增益

实验前无法知道真实 `RMSE_after`，因此只能预测：

```Plain Text
PG_expected(E) = (RMSE_current_best - RMSE_predicted_after(E)) / max(RMSE_current_best, ε)
```

其中：

- `RMSE_current_best`：当前历史最优已知 RMSE，或当前 round baseline RMSE 预测值
- `RMSE_predicted_after(E)`：系统基于历史相似实验、变量类型、候选实验设计估计的实验后 RMSE

若采用归一化供 utility 使用：

```Plain Text
pg_expected_clipped = clip(PG_expected(E), 0, 1)
```


### 7.7 为什么不建议再保留 RMSE_ideal

原文档里出现过：

```Plain Text
RMSE_ideal
```

但当前工程中并不需要这个量。原因是：

- `RMSE_ideal` 很难定义
- 不同任务中理论最优值不稳定
- 引入后会让 PG 的解释变差

因此建议删除 `RMSE_ideal`，统一改为：

- `RMSE_before`
- `RMSE_after`
- `RMSE_current_best`
- `RMSE_predicted_after(E)`

---

## 八、与 Pearson_r 的关系

### 8.1 为什么当前闭环里常看到 `delta_pearson_r`

因为当前科学问题关注的是：

> 加入 `DeltaDec` 后，是否相对 baseline 带来了**增量信息**

所以当前 round 摘要里常打印：

```Plain Text
delta_pearson_r = pearson_r_treatment - pearson_r_baseline
```

这本身没有错，但它不等价于 `PG_actual(E)`。


### 8.2 建议区分两条线

建议系统内明确区分：

1. **增量相关性指标**

```Plain Text
DeltaPearson(E) = Pearson_r_after - Pearson_r_before
```

2. **误差型性能增益**

```Plain Text
PG_actual(E) = (RMSE_before - RMSE_after) / max(RMSE_before, ε)
```

二者都保留，但用途不同：

- `DeltaPearson(E)`：更贴近“增量科学信号”
- `PG_actual(E)`：更贴近“误差下降比例”


### 8.3 如果要统一多指标性能增益

若后续希望兼顾 `RMSE` 与 `Pearson_r`，建议定义一个加权综合性能增益：

```Plain Text
PG_multi(E) = λ * PG_RMSE(E) + (1 - λ) * PG_Pearson(E)
```

其中：

```Plain Text
PG_RMSE(E)    = (RMSE_before - RMSE_after) / max(RMSE_before, ε)
PG_Pearson(E) = (Pearson_after - Pearson_before) / max(1 - Pearson_before, ε)
```

建议：

- 内部 utility 默认仍优先用 `PG_RMSE`
- `DeltaPearson` 作为辅助解释信号
- 不在当前版本一次性把 utility 改成多指标混合，先保持简单可控

---

## 九、建议的程序落地规则

### 9.1 第一轮

第一轮候选实验选择时：

```Plain Text
β = 0
U(E) = α·IG(E) - γ·Risk(E) - δ·Cost(E)
```

原因：

- 无历史实验结果
- `PG_expected(E)` 缺乏可靠训练基础


### 9.2 第二轮及以后

从第二轮开始：

```Plain Text
U(E) = α·IG(E) + β·PG_expected(E) - γ·Risk(E) - δ·Cost(E)
```

实验执行后：

- 写入 `pg_actual_signed`
- 写入 `pg_actual_clipped`
- 写入 `delta_pearson_r`
- 供下一轮 `PG_expected(E)` 估计器学习


### 9.3 建议存储字段

建议在 `ExperimentResult` 或 evaluation summary 中增加：

```json
{
  "baseline_rmse": 12.4,
  "treatment_rmse": 11.7,
  "baseline_pearson_r": 0.41,
  "treatment_pearson_r": 0.51,
  "delta_pearson_r": 0.10,
  "pg_actual_signed": 0.0565,
  "pg_actual_clipped": 0.0565
}
```

---

## 十、与当前代码的差距

### 10.1 当前 `decision_unified.py` 现状

当前 `core/decision_unified.py` 已实现：

- `estimated_information_gain`
- `estimated_performance_gain`
- `estimated_risk`
- `estimated_cost`
- `utility_score`

但其中：

- `estimated_performance_gain` 仍是启发式规则
- proposer 和 questioner 仍未在主链里正式并行
- 角色模型路由尚未配置化


### 10.2 下一步建议改动点

建议后续实际开发时，优先改以下位置：

1. `runtime_config.py`
   - 增加 `llm_role_models`

2. `planner_unified.py`
   - 接入 proposer/questioner 并行编排器

3. `decision_unified.py`
   - 新增 `PG_expected(E)` 的明确估计函数

4. `evaluation_unified.py`
   - 增加 `pg_actual_signed / pg_actual_clipped`
   - 同时保留 `baseline/treatment/delta` 三组核心指标

5. `scripts/run_real_api_two_round_demo.py`
   - 与正式链保持同样的角色模型映射

---

## 十一、实施检查清单

| 任务 | 状态 | 说明 |
|---|---|---|
| proposer + questioner 并行方案 | ✅ 已定稿 | 作为首个并行点 |
| 角色模型分配方案 | ✅ 已定稿 | `plus / 3.8-max` 混合 |
| PI审批节点保留 | ✅ 已明确 | 不改变 |
| `PG_actual(E)` 公式修正 | ✅ 已定稿 | 采用 RMSE 改善比例 |
| `PG_expected(E)` 定义补全 | ✅ 已定稿 | 采用实验前预测值 |
| `RMSE_ideal` 去除建议 | ✅ 已明确 | 避免歧义 |
| `delta_pearson_r` 与 `PG` 区分 | ✅ 已明确 | 一条是增量相关性，一条是误差型增益 |
| 后续程序修改入口 | ✅ 已梳理 | `runtime_config / planner_unified / decision_unified / evaluation_unified` |

---

## 十二、一句话总结

**本次推荐将推理规划层升级为“proposer/questioner 并行 + 关键裁决角色使用高质量模型”的混合方案；同时将性能增益明确拆分为 `PG_expected(E)` 与 `PG_actual(E)`，其中实验后实际增益采用你给出的 RMSE 下降比例公式，并与 `delta_pearson_r` 分开存储和解释。**
