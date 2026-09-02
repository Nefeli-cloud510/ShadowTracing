# Shadow Tracing 前端设计文档（轴式闭环版）

> 本文档用于正式冻结“逐影 Shadow Tracing”前端设计方向，作为后续前端架构开发的直接依据。
> 
> 当前前端主方向不再采用“六层模块分别做成独立主页面”的传统后台式布局，而采用：
> 
> **主页面 = 轴式轮次闭环 Timeline**
> 
> 以 `Round` 为区间、以科研步骤为节点、以假设树为分支、以节点详情页为深入展开方式。

---

## 一、设计背景与依据

### 1.1 设计依据

本方案综合以下来源形成：

1. 用户提供的前端布局草案  
   [ShadowTracing前端设计.md](file:///D:/ST_doc/ShadowTracing%E5%89%8D%E7%AB%AF%E8%AE%BE%E8%AE%A1.md)

2. 当前项目已落地的后端闭环能力  
   [session_handoff_2026-09-01.md](file:///D:/Shadow-Tracing-simple/docs/session_handoff_2026-09-01.md)

3. 当前 LLM / RAG / 状态写回主链的接口约束  
   [llm_rag_interfaces.md](file:///D:/Shadow-Tracing-simple/docs/llm_rag_interfaces.md)

4. 当前统一状态与审计主链  
   [AUDIT_CHECKLIST.md](file:///D:/Shadow-Tracing-simple/state/AUDIT_CHECKLIST.md)


### 1.2 当前项目现实约束

前端设计必须服从当前项目的实际开发状态，不能脱离后端实现空想。

当前后端已经具备以下基础：

- `task -> planner_input -> candidate_experiments -> PI审批 -> protocol -> execution -> evaluation -> writeback` 的统一主链
- `hypothesis_tree.json`、`uncertainties.json`、`experiment_memory.json`、`decision_log.json` 等核心状态文件
- 两轮真实闭环的状态写回和审计链
- `PG_expected(E)` 与 `PG_actual(E)` 已接入决策层和评价层
- proposer / questioner 并行、关键角色分模型能力已接入

因此，前端无需从零定义业务对象，而应直接围绕这些现有状态设计展示与交互。

---

## 二、产品定位

### 2.1 一句话定义

**Shadow Tracing Frontend = 面向科研闭环的可视化流程控制台**


### 2.2 前端的三项核心职责

前端的职责按优先级排序如下：

1. **可视化科研闭环过程**
2. **提供人在环控制入口**
3. **让状态、证据、实验与假设更新可追溯**


### 2.3 明确不做什么

前端不应被设计成：

- 普通的 BI 大屏
- 普通的聊天产品
- 纯模块列表式后台
- 纯图表页拼接

前端必须首先回答这个问题：

> “这个系统是怎样从科学问题出发，生成假设、规划实验、执行实验、解释结果，并进入下一轮的？”

---

## 三、总设计方向

### 3.1 总体方向

当前正式采用：

**轴式轮次闭环主页面 + 节点驱动交互 + 假设树分支联动**


### 3.2 总设计原则

- 主页面以横向时间轴为骨架，从左到右表示闭环推进
- 每个 `Round` 是主轴上的一个独立区间
- 每个关键科研步骤是主轴上的一个节点组件
- 节点上下延伸出与该步骤相关的分支信息
- 主页面用于“看清闭环”，详细内容用独立详情页承接
- 第一轮完整打底，后续轮次默认折叠更多细节
- 默认模式采用 `Work Mode`


### 3.3 视觉原则

- 页面外部：浅中性底
- 框内主题：深色外壳 + 浅纸面工作区
- 核心配色集中使用：
  - `#25578F`
  - `#A4926A`
  - `#0F2142`
  - `#0C2A5F`
  - `#767974`
- 采用构成主义风格组织组件：
  - 强轴线
  - 清晰分区
  - 几何按钮
  - 规则分支
  - 克制的装饰性轨迹线

---

## 四、信息架构

## 4.1 页面结构

建议前端采用：

- `1 个主页面`
- `4 个辅助页面`
- `1 个答辩页`


### 4.1.1 主页面

- `Closed Loop Timeline`

这是默认首页，也是核心页面。


### 4.1.2 辅助页面

- `Mission`
- `Knowledge & Memory`
- `Experiment & Evaluation`
- `Governance & Decisions`


### 4.1.3 答辩页

- `Story Replay`


## 4.2 各页面职责

### Closed Loop Timeline

主页面。以 `Round` 为区间，从左到右展示完整科研闭环。


### Mission

任务定义页。用于结构化输入科研问题、目标变量、约束边界、评价标准与 PI 初始指导。


### Knowledge & Memory

长期状态页。查看双知识库、完整假设树历史、不确定性记忆与实验记忆。


### Experiment & Evaluation

实验细节页。查看实验协议、执行状态、图表、科学解释与回写影响。


### Governance & Decisions

治理页。查看 PI 审批记录、决策日志、暂停/恢复/驳回历史与轮次总结。


### Story Replay

答辩回放页。面向评委，按“故事线”自动播放两轮闭环。

---

## 五、主页面设计：Closed Loop Timeline

这是整个前端最核心的页面。

## 5.1 页面骨架

主页面建议结构如下：

1. 顶部：项目头部区
2. 中部：横向闭环主轴
3. 底部：Mini Map / Round 缩略条

注意：

- 主页面不再承担所有详细信息
- 主页面只负责“讲清楚科研闭环”
- 具体节点的深度内容用独立详情页承接


## 5.2 顶部区域

顶部信息建议保持简洁，只保留关键内容：

- 项目名
- 当前科学问题摘要
- 当前 round
- 当前阶段
- 模式切换：`Work / Story`
- 全局搜索或跳转

布局建议：

- 左：标题与问题摘要
- 中：round / stage 状态
- 右：快捷入口 / 搜索 / 模式切换

说明：

- 未初始化任务时，标题区保留，但科学问题摘要为空
- 已有任务时，顶部直接显示当前研究问题


## 5.3 主轴定义

主轴从左到右贯穿页面，是整个系统的流程主干。

每个 `Round` 占据一段固定区间。

每个区间内部节点顺序固定为：

1. `Q` 科学问题输入
2. `K` 知识注入 / RAG
3. `H` 假设生成
4. `C` 科学质询
5. `U` 不确定性识别
6. `E` 候选实验与综合价值
7. `P` PI 审批
8. `X` 实验执行
9. `A` 分析评价
10. `W` 状态回写


## 5.4 节点组件设计

每个节点是主轴上的圆形或圆角按钮组件。

节点包含：

- 图标
- 简称
- 状态表现
- 点击行为

节点视觉状态：

- `未开始`
- `进行中`
- `已完成`
- `等待审批`
- `已暂停`
- `异常`

颜色建议：

- 未开始：灰暗
- 进行中：蓝色高亮
- 已完成：浅底深字
- 等待审批：金色强调
- 已暂停：灰描边
- 异常：深灰 + 警示标记


## 5.5 Round 区间设计

每个 `Round` 是时间轴上的一个连续科研区段。

区间头建议显示：

- `Round n`
- 当前状态标签
- 当前阶段标签

区间表现建议：

- 不用厚重卡片整体包裹
- 用轻分隔线 / 几何区块做层级区分
- 保持主轴连续

---

## 六、各节点如何落地

下面逐个说明节点的页面含义、点击行为、与后端映射。

## 6.1 Q 节点：科学问题输入

### 页面职责

该节点表示科研任务的定义入口。


### 在哪里输入

科学问题输入设置在两个地方：

1. `Mission` 页面  
   用于完整结构化输入科研任务

2. 主轴上的 `Q` 节点  
   用于流程视图中的映射与补充


### 点击行为

点击 `Q` 节点后：

- 若任务尚未初始化：
  - 进入 `Mission` 详情页或会话输入页
- 若任务已存在：
  - 打开该任务的详情页，查看：
    - 科学问题
    - 目标变量
    - 约束
    - 评价指标
    - PI guidance 历史


### 和后端映射

该节点对应：

- `task.json`
- `process.json`
- `decision_log.json`


## 6.2 K 节点：知识注入 / RAG

### 页面职责

表示系统在当前轮使用知识库和项目资料做上下文增强。


### 点击行为

点击后进入详情页，显示：

- 项目信息库命中摘要
- 文献知识库命中摘要
- 当前轮使用的 RAG 片段
- 哪些证据被下游假设生成或质询使用


### 和后端映射

优先基于：

- `llm_rag_interfaces.md` 中定义的输入输出
- `planner_input` 中已落盘的知识增强内容


## 6.3 H 节点：假设生成

### 页面职责

表示 `HypothesisProposer` 在当前轮生成的核心假设分支。


### 主页面表现

该节点上方长出局部假设树。


### 点击行为

点击后进入详情页，显示：

- 当前轮新生成的假设节点
- 假设摘要
- 对应预测
- 证伪条件
- 与前一轮相比新增了哪些节点


### 和后端映射

该节点对应：

- `hypothesis_tree.json`
- `planner_output`
- `planner_input`


## 6.4 C 节点：科学质询

### 页面职责

表示 `ScientificQuestioner` 的输出，即：

- 对现有假设的批判
- 当前逻辑缺口
- 关键科学分歧


### 点击行为

点击后进入详情页，显示：

- 当前轮识别出的质询点
- 对应假设
- 对应不确定性候选


### 和后端映射

对应：

- `planner_input` 中的质询类 traces
- 不确定性前置生成逻辑


## 6.5 U 节点：不确定性识别

### 页面职责

表示从假设分歧中提炼出的高优先级科学不确定性。


### 主页面表现

该节点建议在主轴下方展开 1-2 个关键不确定性卡片。


### 点击行为

点击后进入详情页，显示：

- 优先级排序
- resolution status
- 关联假设
- 推荐区分实验


### 和后端映射

对应：

- `uncertainties.json`
- `uncertainty_priority`


## 6.6 E 节点：候选实验与综合价值

### 页面职责

表示当前轮生成的候选实验及其综合价值计算结果。


### 主页面表现

在主轴下方展开实验矩阵：

- 最多展示 3 个候选实验
- 推荐实验用金色强调


### 点击行为

点击后进入详情页，显示：

- `IG`
- `PG_expected`
- `Risk`
- `Cost`
- `U(E)`
- target hypothesis
- distinguishing condition


### 和后端映射

对应：

- `candidate_experiments`
- `decision_unified`
- `planner_output`


## 6.7 P 节点：PI 审批

### 页面职责

表示人在环决策节点。


### 主页面表现

该节点状态必须高可见，默认强调。


### 点击行为

进入详情页后显示：

- 当前推荐实验
- 目标假设
- 不确定性
- 风险
- 成本
- 推荐理由

操作：

- 批准
- 要求修改
- 驳回
- 暂停本轮


### 和后端映射

对应：

- `decision_log.json`
- `process.json`
- `planner_input.json`


## 6.8 X 节点：实验执行

### 页面职责

表示 protocol 已通过审批并开始进入统一执行器。


### 点击行为

进入详情页后显示：

- 协议摘要
- 执行步骤
- 执行状态
- 产物路径
- 是否完成


### 和后端映射

对应：

- `protocol`
- `execution result`
- `experiment_memory`


## 6.9 A 节点：分析评价

### 页面职责

表示实验结果的解释前台。


### 点击行为

进入详情页后显示：

- baseline vs treatment
- `delta_pearson_r`
- `delta_rmse`
- `pg_actual`
- 稳定性判断
- supports / weakens / mixed
- 图表入口


### 和后端映射

对应：

- `evaluation`
- `planner_evaluation_summary`


## 6.10 W 节点：状态回写

### 页面职责

表示实验结果如何反馈到系统知识状态。


### 点击行为

进入详情页后显示：

- 哪些假设受到影响
- 哪些不确定性被解决/降低
- 哪些实验记忆被新增
- 下一轮 planner_input 如何变化


### 和后端映射

对应：

- `hypothesis_tree.json`
- `uncertainties.json`
- `experiment_memory.json`
- `planner_input.json`
- `planner_output.json`

---

## 七、假设树设计

假设树是整个前端的第一视觉重点。

## 7.1 主页面上的假设树

主页面不展示完整树，只展示局部科研状态树。

规则：

- 在 `H` 节点上方显示当前轮生成的局部树
- 在 `W` 节点上方显示回写后的局部树
- 形成前后对照


## 7.2 节点视觉规则

- `active`：蓝色高亮
- `newly_split`：金色描边
- `observing`：浅蓝灰
- `pruned`：低透明
- `supported`：描边增强
- `weakened`：饱和度降低


## 7.3 主页面限制

主页面默认只显示两层树结构：

- 第一层：主假设
- 第二层：关键分裂

更深层级仅在详情页和 `Knowledge & Memory` 页面中查看。


## 7.4 完整树页面

完整树放在 `Knowledge & Memory` 页面，支持：

- Round 切换
- diff 对比
- 按状态筛选
- 查看支持度变化历史

---

## 八、科学解释与结果反馈设计

## 8.1 科学解释位置

科学解释主要落在两个节点：

- `A` 节点：解释前台
- `W` 节点：反馈后台


## 8.2 A 节点负责什么

负责向用户展示实验结果意味着什么：

- 有没有提升
- 提升是否稳定
- 当前结果更支持哪条假设


## 8.3 W 节点负责什么

负责回答：

- 结果改变了哪些状态
- 哪些假设被增强或削弱
- 哪些不确定性被解决
- 下一轮方向是什么

---

## 九、节点详情页方案

这是本次设计方案中的一个重要变化。

## 9.1 不再把一切都堆在主页面

主页面仅保留：

- 主轴
- 节点状态
- 局部树杈
- 极简摘要

详细内容用独立页面承接。


## 9.2 为什么采用详情页

原因不是服务器扛不住“页面数量”，而是：

- 主页面如果承载所有复杂图表和会话，信息会严重过载
- 横向时间轴会被过多细节破坏
- 节点级上下文天然适合独立路由

前端性能上更稳妥的策略是：

- 主页面轻量化
- 节点详情页按需加载
- 页面级懒加载
- 详情数据按节点请求


## 9.3 建议路由形式

建议采用：

- `/timeline`
- `/timeline/round/:roundId/node/:nodeId`

例如：

- `/timeline/round/1/node/Q`
- `/timeline/round/2/node/H`
- `/timeline/round/2/node/P`


## 9.4 详情页内容结构

每个详情页统一采用：

1. 顶部：节点标题 + round + 状态
2. 左侧：当前节点的结构化信息
3. 右侧：中央智能体交互 / 详情抽屉
4. 底部：相关对象联动

---

## 十、如何解决“越做越长”

这是该方案的核心难点，必须提前约束。

## 10.1 双层时间轴

主页面采用：

- 总览层：所有 round 的骨架
- 展开层：某个 round 的详细区段


## 10.2 默认折叠策略

默认规则：

- `Round 1`：展开更多
- `Round 2+`：折叠更多

Round 2+ 默认只显示：

- 当前活跃节点
- 当前关键树分支
- 当前推荐实验
- 当前回写摘要


## 10.3 分支数量限制

每轮主页面最多显示：

- 2-4 个核心假设节点
- 1-2 个关键不确定性
- 3 个候选实验以内
- 1 个推荐实验
- 1 个评价摘要


## 10.4 Mini Map

底部保留一条缩略 timeline：

- 用于快速跳转 round
- 避免横向过长迷路

---

## 十一、辅助页面设计

## 11.1 Mission

用于任务定义与 PI 初始输入。

包含：

- 科学问题
- 目标变量
- 约束
- 评价标准
- 初始 PI guidance


## 11.2 Knowledge & Memory

用于长期状态与版本对比。

包含：

- 项目信息库
- 文献知识库
- 假设树历史版本
- uncertainty queue
- experiment memory


## 11.3 Experiment & Evaluation

用于实验执行与图表展示。

包含：

- 协议详情
- 执行状态
- 结果图表
- 稳健性分析
- 科学解释


## 11.4 Governance & Decisions

用于人工治理与审计。

包含：

- PI 审批记录
- 决策日志
- 暂停/恢复历史
- 轮次总结


## 11.5 Story Replay

用于答辩回放。

包含：

- 两轮完整闭环时间线
- 关键节点自动播放
- 假设树前后变化
- 关键科学结论摘要

---

## 十二、前端组件架构

## 12.1 主页面组件

- `ClosedLoopTimelinePage`
- `TimelineHeader`
- `TimelineAxis`
- `RoundSegment`
- `TimelineNode`
- `HypothesisBranchTree`
- `UncertaintyBranch`
- `ExperimentBranchMatrix`
- `EvaluationSummaryInline`
- `TimelineMiniMap`


## 12.2 详情页组件

- `NodeDetailPage`
- `NodeHeader`
- `NodeContentPanel`
- `AgentInteractionPanel`
- `PiReviewCard`
- `WritebackImpactPanel`


## 12.3 辅助页面组件

- `MissionFormPanel`
- `KnowledgeLibraryPanel`
- `HypothesisTreeHistoryPanel`
- `ExperimentExecutionPanel`
- `DecisionLogTimeline`
- `StoryReplayPlayer`

---

## 十三、前端状态结构建议

前端 store 建议按现有后端领域对象组织：

- `task`
- `process`
- `decisionLog`
- `hypothesisTree`
- `uncertainties`
- `experimentMemory`
- `plannerInput`
- `plannerOutput`
- `currentRound`
- `currentNode`
- `storyMode`

说明：

- 不建议重新发明一套前端专属数据模型
- 优先与后端状态对象对齐
- 这样后续 API 接入、状态调试和审计会更顺

---

## 十四、与当前项目实现的映射关系

当前前端设计与项目状态链的主要映射如下：

### 14.1 任务与治理

- `task.json`
- `process.json`
- `decision_log.json`


### 14.2 假设与不确定性

- `hypothesis_tree.json`
- `uncertainties.json`


### 14.3 实验与评价

- `experiment_memory.json`
- `planner_evaluation_summary`
- `evaluation`


### 14.4 规划输入输出

- `planner_input.json`
- `planner_output.json`

---

## 十五、开发阶段建议

## 15.1 第一阶段：静态样例驱动

目标：

- 跑通页面结构和交互范式

优先做：

- 主轴
- Round 区块
- 节点状态
- 局部假设树
- 节点详情页骨架


## 15.2 第二阶段：接入真实状态

接入当前已稳定的状态对象：

- `task`
- `process`
- `hypothesis_tree`
- `uncertainties`
- `experiment_memory`
- `decision_log`
- `evaluation summary`


## 15.3 第三阶段：接入实时闭环流程

目标：

- 节点状态动态刷新
- 审批动作可提交
- 评价后自动回写高亮
- timeline 自动延长到下一轮

---

## 十六、当前已确认设计口径

以下口径已确认，可直接作为开发基线：

1. 主页面默认模式：`Work`
2. `Round 1` 默认展开更多
3. `Round 2+` 默认折叠更多
4. 主页面假设树默认只展示 2 层
5. 节点详细信息允许单独页面展开
6. PI 审批允许直接在前端主链中完成

---

## 十七、当前仍需保留的未决问题

以下问题不阻碍开发启动，但应在实现过程中继续细化：

## 17.1 主页面与详情页的切换方式

待最终确认：

- 点击节点后默认进入新页面
- 是否保留轻量悬浮预览

当前建议：

- 默认进入节点详情页
- 主页面仅保留轻量 hover 提示


## 17.2 Round 数量增加后的横向导航方式

待后续决定：

- 使用横向滚动
- 或使用分页式切换

当前建议：

- 先做横向滚动 + Mini Map


## 17.3 Story Replay 是否首期实现

当前建议：

- 第一版先完成主页面 + Mission + 节点详情页
- `Story Replay` 可作为第二阶段展示增强

---

## 十八、最终建议

这套方案正式确定了前端主方向：

**用“轴式轮次闭环主页面”替代传统功能后台，用“节点详情页”承接深入交互，用“局部假设树 + 状态回写”体现作品的科研本质。**

这条路线的优点是：

- 贴合比赛展示逻辑
- 贴合评委理解路径
- 贴合当前后端真实状态链
- 可以自然容纳：
  - 科学问题输入
  - 多角色推理
  - 假设树演化
  - 候选实验选择
  - PI 审批
  - 实验评价
  - 状态回写

---

## 十九、建议的下一步

文档冻结后，下一步建议直接进入前端架构开发准备。

优先顺序如下：

1. `ClosedLoopTimelinePage`
2. `RoundSegment + TimelineNode`
3. `NodeDetailPage`
4. `HypothesisBranchTree`
5. `PiReviewCard`
6. `ExperimentBranchMatrix`
7. `Mission 页面`
8. `Knowledge & Memory 页面`

如果后续进入开发，本文件应作为前端架构设计的主依据。
