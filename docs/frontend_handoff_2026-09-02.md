# 逐影 Shadow Tracing - 前端开发交接文档

## 1. 项目与架构概述
- **项目定位**：“挑战杯” AI Scientist 赛道，竞争假设驱动的科研实验闭环系统。
- **前端技术栈**：React 18 + Vite + TypeScript + React Router。
- **UI 设计规范**：平面构成主义、轻磨砂玻璃质感、蓝金配色（#25578F, #A4926A, #0F2142, #0C2A5F, #767974），以 `observatory.png`（观测站星轨）为全局底层背景。
- **核心交互范式**：
  - **主页时间轴 (Axis Timeline)**：将科研闭环抽象为 10 个标准节点（Q/K/H/C/U/E/P/X/A/W），以横向时间轴展现。分支从节点上下生长（上：假设/实验；下：问题/不确定性/评价）。
  - **多页签路由 (Tab System)**：点击主轴节点不覆盖主页，而是像浏览器一样在顶部生成可关闭的新页签。

## 2. 当前已完成进度 (2026-09-02)
1. **基础框架与路由**：已搭建 Vite + React 环境，实现 `TabContext` 全局页签状态管理。
2. **本地真实 JSON 驱动映射**：
   - 实现了 `realStateLoader.ts`，能读取 `public/demo-state/latest/` 下的真实后端状态文件（task, process, hypothesis_tree, decision_log 等）。
   - 根据 `process.json` 的 `current_phase` 和 `current_step` 动态精准推算各个节点的状态（未开始、进行中、已完成、待审批）。
3. **主页 Timeline UI 重构**：
   - 采用 10 列 Grid 布局，完美对齐主轴节点与上下延伸的分支卡片（Branch Card）。
   - 修复了节点遮挡、时间轴右侧截断、背景图透明度过低等视觉问题。
4. **节点详情页 (NodeDetailPage) 深度定制**：
   - **H 节点 (假设生成)**：根据真实树结构渲染阶梯缩进的假设树列表，展示支持度与状态。
   - **E 节点 (候选实验)**：渲染 IG、PG、Cost 评估矩阵，并高亮系统推荐实验。
   - **P 节点 (PI 审批)**：从 `decision_log` 提取人工审批记录与自然语言反馈（Feedback）并按时间线渲染。

## 3. 待开发任务 (TODO)
接手的智能体需要优先处理以下任务以完成最终闭环演示：

1. **核心数据流接入 (Local JSON -> Live API)**：
   - 目前数据是静态读取 `public/demo-state` 下的 JSON 快照。需对接后端真实的 WebSocket 或 RESTful API，实现前端状态随系统运行实时刷新。
2. **完善剩余节点详情页**：
   - **X 节点 (实验执行)**：需补充具体 protocol 产物展示。
   - **A 节点 (分析评价)**：需引入图表库（如 ECharts/Recharts），渲染真实值 vs 预测值的折线图、Baseline vs Treatment 的对比图（展示 RMSE / Pearson R）。
3. **多轮次 (Multi-round) 动态渲染**：
   - 目前主页主要渲染最新的一轮（Round Segment）。需完善轮次递进逻辑，当 Round 1 结束进入 Round 2 时，时间轴能自然向右延伸或支持轮次切换查看。
4. **辅助页面开发 (低优先级，视答辩需求而定)**：
   - `Mission`（任务输入配置页）。
   - `Knowledge & Memory`（全局知识库与记忆展示页）。
   - `Story Replay`（用于答辩的一键自动回放演示模式）。

## 4. 核心文件指引
- `src/App.tsx` & `src/main.tsx`：应用入口与路由、TabContext 注入。
- `src/contexts/TabContext.tsx`：多页签核心状态管理。
- `src/data/realStateLoader.ts`：后端 JSON 到前端 TimelineBundle 的映射逻辑（核心业务逻辑层）。
- `src/components/RoundSegment.tsx`：单轮时间轴及上下分支卡片的渲染组件。
- `src/pages/NodeDetailPage.tsx`：节点详情页，包含 H/E/P 等特定节点的专属视图。
- `src/App.css`：全局及各组件样式（包含主视觉背景与构成主义样式设置）。