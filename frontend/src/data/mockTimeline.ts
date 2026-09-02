import type { RoundData, TimelineNodeData } from '../types/timeline'

const roundNodeTemplate: TimelineNodeData[] = [
  {
    id: 'Q',
    shortLabel: 'Q',
    title: '科学问题输入',
    summary: 'PI 定义研究问题、目标变量、约束条件。',
    status: 'completed',
  },
  {
    id: 'K',
    shortLabel: 'K',
    title: '知识注入 / RAG',
    summary: '项目资料与文献知识进入 planner_input。',
    status: 'completed',
  },
  {
    id: 'H',
    shortLabel: 'H',
    title: '假设生成',
    summary: '生成竞争假设并建立局部假设树。',
    status: 'completed',
  },
  {
    id: 'C',
    shortLabel: 'C',
    title: '科学质询',
    summary: '识别逻辑缺口与关键分歧。',
    status: 'completed',
  },
  {
    id: 'U',
    shortLabel: 'U',
    title: '不确定性识别',
    summary: '提炼当前最重要的科学不确定性。',
    status: 'completed',
  },
  {
    id: 'E',
    shortLabel: 'E',
    title: '候选实验',
    summary: '生成候选实验并计算综合价值。',
    status: 'completed',
  },
  {
    id: 'P',
    shortLabel: 'P',
    title: 'PI 审批',
    summary: '人在环决定是否批准推荐实验。',
    status: 'completed',
  },
  {
    id: 'X',
    shortLabel: 'X',
    title: '实验执行',
    summary: '统一执行器按 protocol 运行实验。',
    status: 'completed',
  },
  {
    id: 'A',
    shortLabel: 'A',
    title: '分析评价',
    summary: '比较 baseline 与 treatment 的结果差异。',
    status: 'completed',
  },
  {
    id: 'W',
    shortLabel: 'W',
    title: '状态回写',
    summary: '把结果写回假设树、不确定性和实验记忆。',
    status: 'completed',
  },
]

export const mockRounds: RoundData[] = [
  {
    id: 'round-1',
    title: 'Round 1',
    subtitle: 'bootstrap loop',
    stateLabel: '待输入',
    questionSummary: '',
    nodes: roundNodeTemplate.map((node) => {
      if (node.id === 'Q') {
        return { ...node, status: 'active' }
      }

      return { ...node, status: 'pending' }
    }),
    hypotheses: [],
    uncertainties: [],
    experiments: [],
  },
]
