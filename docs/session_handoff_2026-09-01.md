# Shadow Tracing Session Handoff

## 1. 项目背景

- 项目名称：`逐影 Shadow Tracing`
- 目标：构建“竞争假设驱动的 AI Scientist 科研实验闭环系统”
- 当前科学问题主线：`LHAASO 宇宙线日影南北偏移 DeltaDec 是否包含能够提升太阳风速度 Vsw 预测的有效信息`
- 用户角色：项目负责人 / 架构师 / PI
- AI 角色：编程伙伴，按既定系统架构持续把底层能力做成可运行、可审计、可演示的工程

## 2. 当前总体状态

- 当前工程已经从“程序化闭环原型”发展为“LLM 参与主链的可运行闭环”。
- 已具备：
  - `programmatic / llm` 双模式
  - 两轮闭环测试
  - 审计链
  - 真实百炼模型调用验证
  - 真实百炼知识检索验证
- 当前最准确的状态描述：
  - `stub 驱动的 llm_mode 两轮完整闭环`：已通过
  - `真实 qwen3.8-max 模型调用`：已验证成功
  - `真实百炼知识检索`：已验证成功
  - `真实 API 下的两轮完整全链路闭环`：具备条件，但还缺一条“完整跑完并留档”的最终验活记录

## 3. 六层架构落地情况

### 人工控制层

- 已实现：
  - 科学问题承接后的流程主编排
  - 候选实验审阅
  - 批准 / 拒绝 / 暂停
  - round review
  - continue / adjust 后进入下一轮规划
- 关键文件：
  - `core/control_unified.py`
- 当前特征：
  - PI 审批节点仍保留，LLM 没有绕过人工决策

### 推理规划层

- 已实现角色：
  - `central_controller_llm`
  - `scientific_interpreter_llm`
  - `hypothesis_proposer_llm`
  - `scientific_questioner_llm`
  - `experiment_planner_llm`
- 已实现统一底座：
  - `llm_gateway.py`
  - `planner_unified.py`
- 关键文件：
  - `core/llm_gateway.py`
  - `core/central_controller_llm.py`
  - `core/scientific_interpreter_llm.py`
  - `core/hypothesis_proposer_llm.py`
  - `core/scientific_questioner_llm.py`
  - `core/experiment_planner_llm.py`
  - `core/planner_unified.py`
- 当前特征：
  - 采用“程序基线 + LLM 细化”的安全策略
  - LLM 不直接裸写最终状态，而是输出结构化 schema，再经现有 mapper / applier / updater 落盘

### 知识记忆层

- 已实现：
  - 任务状态文件读写
  - 假设树
  - 不确定性状态
  - 实验记忆
  - 决策日志
  - planner 输入 / 输出文件
- 已实现本地轻量 RAG：
  - 项目状态检索：`state/*.json`
  - 文献文本检索：`outputs/pdf_texts/*.txt`
- 已实现真实百炼知识检索接入口：
  - 官方知识检索接口
  - `workspaceId + agent_id + query + images`
- 关键文件：
  - `core/state_repository.py`
  - `core/state_updater.py`
  - `core/rag_service.py`
  - `state/README.md`
  - `state/AUDIT_CHECKLIST.md`

### 选择决策层

- 已实现：
  - 不确定性排序
  - 候选实验生成
  - 综合价值打分
  - 基于分歧状态的候选实验策略流转
- 关键文件：
  - `core/decision_unified.py`
- 当前特征：
  - 已能消费 planner guidance、generation rationale、不确定性分歧状态

### 执行评价层

- 已实现：
  - 统一执行入口
  - 协议映射
  - 真实 ElasticNet 执行
  - 评价回写
  - disagreement update
  - 执行后 scientific interpreter 写回
- 关键文件：
  - `core/harness_unified.py`
  - `core/protocol_bridge.py`
  - `core/evaluation_unified.py`
  - `core/result_unified.py`
  - `models/elasticnet_runner.py`

### 数据程序层

- 已实现：
  - 本地 CSV 数据读取
  - OMNI + LHAASO 对齐
  - 相对路径数据源配置
  - 窗口化与训练测试切分
- 关键文件：
  - `models/elasticnet_runner.py`
  - `core/protocol_bridge.py`
- 当前不足：
  - 还没有独立的数据质量服务和 artifact registry 服务化拆分

## 4. 当前核心主链

当前 `llm_mode` 主链已经打通到以下程度：

`RAG -> hypothesis proposer / scientific questioner -> hypothesis_generation -> candidate plan -> central controller -> human review -> experiment planner -> protocol -> execution -> evaluation -> scientific interpreter -> state writeback -> next planner_input -> next candidate`

其中：

- `RAG` 在 `_resume_next_round_planning()` 之前运行
- `experiment_planner_llm` 在 `approve_candidate()` 中运行
- `scientific_interpreter_llm` 在 `evaluate_experiment()` 之后、`state writeback` 之前运行

## 5. 关键文件说明

### 主编排与主状态

- `core/control_unified.py`
  - 主流程入口
  - 候选审批、执行、复盘、下一轮重规划
- `core/state_repository.py`
  - 统一状态文件读写
- `core/state_updater.py`
  - 执行后评价与解释增强写回

### LLM / RAG

- `core/runtime_config.py`
  - `.env` 与环境变量统一加载入口
- `core/llm_gateway.py`
  - 百炼模型统一结构化输出网关
- `core/rag_service.py`
  - 本地 + 远程知识检索入口
- `core/central_controller_llm.py`
  - 下一轮 planner_output 的中央控制角色
- `core/scientific_interpreter_llm.py`
  - 执行后结果解释角色
- `core/hypothesis_proposer_llm.py`
  - 假设方向提出角色
- `core/scientific_questioner_llm.py`
  - 质询与新增 uncertainty 角色
- `core/experiment_planner_llm.py`
  - protocol refinement 角色

### 假设 / 不确定性 / 决策

- `core/hypothesis_generation.py`
  - 动态生成和增量扩展假设树
- `core/decision_unified.py`
  - uncertainty prioritizer / candidate generator / utility scorer
- `core/planner_output_applier.py`
  - planner_output 对 candidate / tree / uncertainties 的应用

### 统一 Schema

- `core/unified_schema.py`
  - 全系统 schema 核心
  - 当前大量状态链、审计链都依赖这里

## 6. 测试状态

### 已有关键测试

- `tests/test_human_control_flow.py`
  - 人工控制流主链
- `tests/test_hypothesis_generation.py`
  - 动态假设生成
- `tests/test_decision_layer.py`
  - 选择决策层
- `tests/test_system_audit_closure.py`
  - 两轮审计闭环
- `tests/test_llm_planner_integration.py`
  - llm_mode 接入点测试
- `tests/test_full_llm_closed_loop.py`
  - 两轮 llm_mode 闭环测试
- `tests/test_real_api_optional.py`
  - 真实 API 可选启用 smoke test

### 最近验证结果

- 全量回归已通过：
  - `python -m unittest discover -s tests -v`
- 最新状态：
  - `43` 项通过
  - `2` 项真实 API 测试在未显式启用时跳过

## 7. 当前真实 API 状态

### 模型 API

- 当前已实测：
  - `qwen3.8-max` 可成功返回结构化 JSON
- 当前模型入口：
  - `core/llm_gateway.py`
- 配置来源：
  - `D:\Shadow-Tracing-simple\.env`

### 知识检索 API

- 已对齐到百炼官方接口：
  - `POST https://{workspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/indices/knowledge/search`
  - body:
    - `agent_id`
    - `query`
    - `images`
    - 可选 `agent_version`
- 已真实验证：
  - 返回 `success = true`
  - 顶层结构与官方文档一致
  - `data.nodes[].metadata` 字段总体符合预期
- 当前实现容错：
  - `BAILIAN_WORKSPACE_ID` 即使误填完整 URL，也会自动提取 workspaceId

## 8. 配置说明

### 正确配置文件位置

- 真正生效的文件是：
  - `D:\Shadow-Tracing-simple\.env`
- 模板文件是：
  - `D:\Shadow-Tracing-simple\.env.example`

### 关键配置项

```env
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://llm-jz60biyiqkkwzssm.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
BAILIAN_MODEL=qwen3.8-max

BAILIAN_WORKSPACE_ID=
BAILIAN_KNOWLEDGE_AGENT_ID=
BAILIAN_KNOWLEDGE_AGENT_VERSION=
BAILIAN_KNOWLEDGE_SEARCH_ENDPOINT=

ENABLE_REAL_API_TESTS=0
```

### 注意

- 不要把真实 key 写进 `.env.example`
- 真实 key 只写进 `.env`
- 如果历史上曾把真实 key 写进模板或对话，建议立即轮换

## 9. 当前未完全完成的部分

### 还差最后一次真正意义上的“完全留档”

目前最主要的“未彻底闭环”不是代码结构，而是**缺少一条真实 API 下两轮完整闭环跑完并存档的最终记录**。

现状是：

- `stub + llm_mode` 的两轮闭环已通过
- `真实 qwen` 已通过
- `真实知识检索` 已通过
- 但“真实 API 全链条两轮一起跑完”的最后一次正式验活还需要单独跑完并记录输出

### 原因

- 不是出现明确报错
- 而是远程全链路运行时间较长，上次在安全轮询窗口内没有等到最终结束

### 下一个会话最自然的任务

- 写一条“真实 API 两轮完整闭环验活脚本”
- 要求：
  - 明确阶段日志
  - 明确总超时
  - 每轮完成后打印关键状态
  - 结束后打印：
    - planner mode
    - 是否命中真实知识库
    - 是否有 scientific interpreter 写回
    - 是否完成 round2
    - 是否写出完整 `state/*.json`

## 10. 推荐运行命令

### 全量回归

```powershell
python -m unittest discover -s tests -v
```

### 两轮 LLM 闭环

```powershell
python -m unittest tests.test_full_llm_closed_loop -v
```

### 真实 API 可选 smoke 测试

先在 `.env` 里打开：

```env
ENABLE_REAL_API_TESTS=1
```

再执行：

```powershell
python -m unittest tests.test_real_api_optional -v
```

## 11. 文档入口

- `docs/final_demo_run_guide.md`
- `docs/llm_rag_interfaces.md`
- `state/AUDIT_CHECKLIST.md`

## 12. 给下一个 AI 编程智能体的话

### 先做什么

- 先读：
  - `docs/session_handoff_2026-09-01.md`
  - `docs/final_demo_run_guide.md`
  - `docs/llm_rag_interfaces.md`
  - `state/AUDIT_CHECKLIST.md`
- 再读：
  - `core/control_unified.py`
  - `core/runtime_config.py`
  - `core/rag_service.py`
  - `core/llm_gateway.py`

### 不要做什么

- 不要重写现有 unified 主链
- 不要把 LLM 输出直接写进最终状态，必须继续走 schema + applier / updater
- 不要移除 PI 审批节点
- 不要把真实 key 写进 `.env.example`、测试文件或文档

### 要特别注意什么

- 当前工程的价值在于：
  - 动态假设生成
  - 跨轮闭环
  - 审计链
  - 人机协同节点
- 所以任何新改动都必须保护以下文件的一致性：
  - `hypothesis_tree.json`
  - `uncertainties.json`
  - `experiment_memory.json`
  - `decision_log.json`
  - `planner_input.json`
  - `planner_output.json`

### 下一个最优先任务

- 做“真实 API 两轮完整闭环验活脚本”
- 不要先去扩前端
- 不要先去抽象新框架
- 先把真实远程两轮运行结果留档

### 完成后应输出什么

- 一份真实远程两轮闭环的运行结果摘要
- 一份失败时的阶段定位信息
- 一份状态文件审计结果

## 13. 当前开发完成度判断

- 如果按“程序主链 + llm_mode + 审计链 + 真实 API 单点验证”计算：约 `90%+`
- 如果按“真实 API 下完整两轮闭环正式验收完成”计算：约 `85%~90%`
- 剩下最关键的不是再补模块，而是把“真实两轮远程闭环最终跑完并留档”这件事完成

