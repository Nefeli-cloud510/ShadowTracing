import type {
  ExperimentPreview,
  HypothesisPreviewNode,
  RoundData,
  TimelineDataBundle,
  TimelineNodeData,
  TimelineNodeStatus,
  UncertaintyPreview,
} from '../types/timeline'

type RawTask = {
  task_id: string
  payload?: {
    research_question?: {
      text?: string
      target?: string
      variables?: {
        x?: string
        y?: string
      }
    }
  }
}

type RawProcess = {
  current_round?: number
  current_stage?: string
  current_phase?: string
  current_step?: string
  progress_percentage?: number
  phases?: Record<string, { status?: string; steps?: Record<string, { status?: string; name?: string }> }>
}

type RawHypothesisTree = {
  nodes?: Array<{
    hypothesis_id?: string
    statement?: string
    status?: string
    support_score?: number
    level?: number
    activated_at_round?: number
    support_history?: Array<{
      round?: number
      score?: number
    }>
  }>
}

type RawUncertainties = {
  records?: Array<{
    uncertainty_id?: string
    question?: string
    priority?: string
    resolution_status?: string
    status?: string
  }>
}

type RawExperimentMemory = {
  entries?: Array<{
    experiment_id?: string
    round_id?: number
    status?: string
    protocol_path?: string
    tested_hypotheses?: string[]
    metrics_snapshot?: {
      delta?: {
        pearson_r?: number
      }
      baseline_rmse?: number
      treatment_rmse?: number
      baseline_pearson_r?: number
      treatment_pearson_r?: number
    }
    key_findings?: string[]
  }>
}

type RawDecisionLog = {
  decisions?: Array<{
    decision_type?: string
    summary?: string
    round_id?: number
    made_by?: string
  }>
}

type RawCandidateExperiments = {
  candidates?: Array<{
    experiment_id?: string
    tested_hypotheses?: string[]
    estimated_information_gain?: number | { value?: number | string }
    estimated_performance_gain?: number | { value?: number | string }
    utility_score?: number | string
  }>
}

type RawPlannerInput = {
  source_round_id?: number
  next_round_id?: number
  scientific_question?: string
  evaluation_summary?: {
    delta_pearson_r?: number
    delta_rmse?: number
    stable?: boolean
  }
  unresolved_uncertainties?: Array<{
    uncertainty_id?: string
    question?: string
    priority?: string
    resolution_status?: string
  }>
  active_hypotheses?: Array<{
    hypothesis_id?: string
    statement?: string
    support_score?: number
    status?: string
  }>
}

const PHASE_ORDER = [
  'task_definition',
  'hypothesis_generation',
  'experiment_planning',
  'experiment_execution',
  'result_analysis',
  'decision_making',
  'next_round',
] as const

const SOURCE_FILES = {
  task: '/demo-state/latest/task.json',
  process: '/demo-state/latest/process.json',
  hypothesisTree: '/demo-state/latest/hypothesis_tree.json',
  uncertainties: '/demo-state/latest/uncertainties.json',
  experimentMemory: '/demo-state/latest/experiment_memory.json',
  decisionLog: '/demo-state/latest/decision_log.json',
  candidateExperiments: '/demo-state/latest/candidate_experiments.json',
  plannerInput: '/demo-state/latest/planner_input.json',
}

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`)
  }
  return (await response.json()) as T
}

function mapHypothesisStatus(status?: string): HypothesisPreviewNode['status'] {
  if (status === 'active') return 'active'
  if (status === 'observing') return 'observing'
  return 'weakened'
}

function mapResolutionStatus(status?: string): UncertaintyPreview['resolutionStatus'] {
  if (status === 'resolved') return 'resolved'
  if (status === 'partially_resolved' || status === 'tracking') return 'tracking'
  return 'open'
}

function getPhaseIndex(phase?: string): number {
  if (!phase) {
    return -1
  }

  return PHASE_ORDER.indexOf(phase as (typeof PHASE_ORDER)[number])
}

function getPlanningStepOrder(step?: string): number {
  if (!step?.startsWith('step_')) {
    return 0
  }

  const value = Number(step.replace('step_', ''))
  return Number.isFinite(value) ? value : 0
}

function toNumber(value: number | string | { value?: number | string } | undefined): number {
  if (typeof value === 'number') {
    return value
  }

  if (typeof value === 'string') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
  }

  if (value && typeof value === 'object') {
    return toNumber(value.value)
  }

  return 0
}

function hypothesisStatusAtRound(
  node: NonNullable<RawHypothesisTree['nodes']>[number],
  currentRound: number,
): HypothesisPreviewNode['status'] {
  const activatedAtRound = node.activated_at_round ?? 0
  if (activatedAtRound === currentRound) {
    return 'newly_split'
  }

  return mapHypothesisStatus(node.status)
}

function supportScoreAtRound(
  node: NonNullable<RawHypothesisTree['nodes']>[number],
  currentRound: number,
): number {
  const history = [...(node.support_history ?? [])]
    .filter((item) => (item.round ?? 0) <= currentRound)
    .sort((a, b) => (b.round ?? 0) - (a.round ?? 0))

  return history[0]?.score ?? node.support_score ?? 0
}

function nodeStatusFromProcess(nodeId: string, process: RawProcess): TimelineNodeStatus {
  const currentPhaseIndex = getPhaseIndex(process.current_phase)
  const planningStepOrder = getPlanningStepOrder(process.current_step)

  const phaseMap: Record<string, number> = {
    Q: getPhaseIndex('task_definition'),
    K: getPhaseIndex('hypothesis_generation'),
    H: getPhaseIndex('hypothesis_generation'),
    C: getPhaseIndex('hypothesis_generation'),
    U: getPhaseIndex('experiment_planning'),
    E: getPhaseIndex('experiment_planning'),
    P: getPhaseIndex('experiment_planning'),
    X: getPhaseIndex('experiment_execution'),
    A: getPhaseIndex('result_analysis'),
    W: getPhaseIndex('decision_making'),
  }

  const nodePhaseIndex = phaseMap[nodeId]
  if (nodePhaseIndex < currentPhaseIndex) {
    return 'completed'
  }

  if (nodePhaseIndex > currentPhaseIndex) {
    return 'pending'
  }

  if (nodeId === 'U') {
    return planningStepOrder >= 1 ? 'completed' : 'active'
  }

  if (nodeId === 'E') {
    return planningStepOrder >= 3 ? 'completed' : planningStepOrder >= 2 ? 'active' : 'pending'
  }

  if (nodeId === 'P') {
    if (process.current_stage === 'awaiting_human_approval' || planningStepOrder === 4) {
      return 'approval'
    }
    return planningStepOrder > 4 ? 'completed' : 'pending'
  }

  if (nodeId === 'Q' || nodeId === 'K' || nodeId === 'H' || nodeId === 'C') {
    return 'active'
  }

  return 'active'
}

function buildNodeDetails(
  nodeId: string,
  task: RawTask,
  process: RawProcess,
  hypothesisTree: RawHypothesisTree,
  uncertainties: RawUncertainties,
  experimentMemory: RawExperimentMemory,
  decisionLog: RawDecisionLog,
  candidateExperiments: RawCandidateExperiments,
  plannerInput: RawPlannerInput,
): string[] {
  const currentRound = process.current_round ?? 1
  const currentRoundDecisions = (decisionLog.decisions ?? []).filter(
    (item) => (item.round_id ?? currentRound) === currentRound,
  )
  const latestEntry = [...(experimentMemory.entries ?? [])]
    .filter((entry) => (entry.round_id ?? 0) <= currentRound)
    .sort((a, b) => (b.round_id ?? 0) - (a.round_id ?? 0))[0]

  switch (nodeId) {
    case 'Q':
      return [
        task.payload?.research_question?.text ?? '暂无科学问题',
        `目标变量：${task.payload?.research_question?.target ?? '未定义'}`,
      ]
    case 'K':
      return [
        `任务关键词：${task.payload?.research_question?.variables?.x ?? '未定义'} -> ${
          task.payload?.research_question?.variables?.y ?? task.payload?.research_question?.target ?? '未定义'
        }`,
        `当前轮规划来源：round ${plannerInput.source_round_id ?? currentRound}`,
      ]
    case 'H':
      return (hypothesisTree.nodes ?? [])
        .filter((node) => (node.activated_at_round ?? 0) <= currentRound)
        .sort(
          (a, b) => supportScoreAtRound(b, currentRound) - supportScoreAtRound(a, currentRound),
        )
        .slice(0, 4)
        .map((node) => `${node.hypothesis_id} · ${supportScoreAtRound(node, currentRound).toFixed(3)}`)
    case 'C':
      return currentRoundDecisions
        .filter(
          (item) =>
            item.decision_type?.includes('scientific_interpreter') ||
            item.decision_type?.includes('planner_output'),
        )
        .slice(-3)
        .map((item) => `${item.made_by ?? 'system'} · ${item.summary}`)
    case 'U':
      return (uncertainties.records ?? [])
        .slice(0, 3)
        .map((item) => `${item.uncertainty_id} · ${item.question}`)
    case 'E':
      return (candidateExperiments.candidates ?? [])
        .slice(0, 3)
        .map((item) => `${item.experiment_id} · U(E) ${toNumber(item.utility_score).toFixed(3)}`)
    case 'P':
      return currentRoundDecisions
        .filter(
          (item) =>
            item.decision_type?.includes('experiment') || item.decision_type?.includes('round'),
        )
        .slice(-3)
        .map((item) => `${item.decision_type} · ${item.summary}`)
    case 'X':
      return latestEntry
        ? [
            `实验：${latestEntry.experiment_id ?? 'unknown'}`,
            `协议：${latestEntry.protocol_path ?? '未记录'}`,
            `状态：${latestEntry.status ?? 'unknown'}`,
          ]
        : ['当前轮尚未执行实验']
    case 'A':
      if (!latestEntry?.metrics_snapshot) return ['暂无评价结果']
      return [
        `baseline Pearson_r：${(latestEntry.metrics_snapshot.baseline_pearson_r ?? 0).toFixed(4)}`,
        `treatment Pearson_r：${(latestEntry.metrics_snapshot.treatment_pearson_r ?? 0).toFixed(4)}`,
        `delta_pearson_r：${(latestEntry.metrics_snapshot.delta?.pearson_r ?? 0).toFixed(4)}`,
      ]
    case 'W':
      return [
        `当前阶段：${process.current_phase ?? 'unknown'}`,
        `下一轮：${plannerInput.next_round_id ?? '未生成'}`,
      ]
    default:
      return []
  }
}

function buildTimelineNodes(
  task: RawTask,
  process: RawProcess,
  hypothesisTree: RawHypothesisTree,
  uncertainties: RawUncertainties,
  experimentMemory: RawExperimentMemory,
  decisionLog: RawDecisionLog,
  candidateExperiments: RawCandidateExperiments,
  plannerInput: RawPlannerInput,
): TimelineNodeData[] {
  const definitions: Array<Pick<TimelineNodeData, 'id' | 'shortLabel' | 'title' | 'summary'>> = [
    { id: 'Q', shortLabel: 'Q', title: '科学问题输入', summary: '查看和编辑当前 scientific task。' },
    { id: 'K', shortLabel: 'K', title: '知识注入 / RAG', summary: '查看当前轮引入的项目资料与文献上下文。' },
    { id: 'H', shortLabel: 'H', title: '假设生成', summary: '查看当前活跃假设与竞争假设分支。' },
    { id: 'C', shortLabel: 'C', title: '科学质询', summary: '查看当前轮分歧、质询与解释增强记录。' },
    { id: 'U', shortLabel: 'U', title: '不确定性识别', summary: '查看当前关键未解决不确定性。' },
    { id: 'E', shortLabel: 'E', title: '候选实验', summary: '查看候选实验与综合价值。' },
    { id: 'P', shortLabel: 'P', title: 'PI 审批', summary: '查看人工审批和决策记录。' },
    { id: 'X', shortLabel: 'X', title: '实验执行', summary: '查看实验执行与 protocol 产物。' },
    { id: 'A', shortLabel: 'A', title: '分析评价', summary: '查看 baseline / treatment 与评价结果。' },
    { id: 'W', shortLabel: 'W', title: '状态回写', summary: '查看假设、不确定性与下一轮输入的回写结果。' },
  ]

  return definitions.map((node) => ({
    ...node,
    status: nodeStatusFromProcess(node.id, process),
    detailItems: buildNodeDetails(
      node.id,
      task,
      process,
      hypothesisTree,
      uncertainties,
      experimentMemory,
      decisionLog,
      candidateExperiments,
      plannerInput,
    ),
  }))
}

export async function loadTimelineBundle(): Promise<TimelineDataBundle> {
  const [
    task,
    process,
    hypothesisTree,
    uncertainties,
    experimentMemory,
    decisionLog,
    candidateExperiments,
    plannerInput,
  ] = await Promise.all([
    readJson<RawTask>(SOURCE_FILES.task),
    readJson<RawProcess>(SOURCE_FILES.process),
    readJson<RawHypothesisTree>(SOURCE_FILES.hypothesisTree),
    readJson<RawUncertainties>(SOURCE_FILES.uncertainties),
    readJson<RawExperimentMemory>(SOURCE_FILES.experimentMemory),
    readJson<RawDecisionLog>(SOURCE_FILES.decisionLog),
    readJson<RawCandidateExperiments>(SOURCE_FILES.candidateExperiments),
    readJson<RawPlannerInput>(SOURCE_FILES.plannerInput),
  ])

  const currentRound = process.current_round ?? 1

  const hypotheses: HypothesisPreviewNode[] = (hypothesisTree.nodes ?? [])
    .filter((item) => (item.activated_at_round ?? 0) <= currentRound)
    .sort((a, b) => supportScoreAtRound(b, currentRound) - supportScoreAtRound(a, currentRound))
    .slice(0, 4)
    .map((item, index) => ({
      id: item.hypothesis_id ?? `H${index + 1}`,
      label: item.statement ?? '未命名假设',
      status: hypothesisStatusAtRound(item, currentRound),
      supportScore: supportScoreAtRound(item, currentRound),
    }))

  const uncertaintyPreviews: UncertaintyPreview[] = (uncertainties.records ??
    plannerInput.unresolved_uncertainties ??
    [])
    .slice(0, 3)
    .map((item, index) => ({
      id: item.uncertainty_id ?? `U${index + 1}`,
      title: item.question ?? '未命名不确定性',
      priority:
        item.priority === 'high' ? 'P1' : item.priority === 'medium' ? 'P2' : 'P3',
      resolutionStatus: mapResolutionStatus(item.resolution_status),
    }))

  const experiments: ExperimentPreview[] = (candidateExperiments.candidates ?? [])
    .slice(0, 3)
    .map((item, index) => ({
      id: item.experiment_id ?? `E_${index + 1}`,
      targetHypothesis: item.tested_hypotheses?.[0] ?? 'unknown',
      utility: toNumber(item.utility_score),
      informationGain: toNumber(item.estimated_information_gain),
      performanceGain: toNumber(item.estimated_performance_gain),
      status: index === 0 ? 'recommended' : 'candidate',
    }))

  const latestExperiment = [...(experimentMemory.entries ?? [])].sort(
    (a, b) => (b.round_id ?? 0) - (a.round_id ?? 0),
  ).find((entry) => (entry.round_id ?? 0) <= currentRound)

  const round: RoundData = {
    id: `round-${currentRound}`,
    title: `Round ${currentRound}`,
    subtitle: process.current_phase ?? 'in progress',
    stateLabel: process.current_stage ?? 'unknown',
    questionSummary:
      task.payload?.research_question?.text ?? plannerInput.scientific_question ?? '',
    nodes: buildTimelineNodes(
      task,
      process,
      hypothesisTree,
      uncertainties,
      experimentMemory,
      decisionLog,
      candidateExperiments,
      plannerInput,
    ),
    hypotheses,
    uncertainties: uncertaintyPreviews,
    experiments,
    evaluation: latestExperiment?.metrics_snapshot
      ? {
          deltaPearsonR: latestExperiment.metrics_snapshot.delta?.pearson_r ?? 0,
          pgActual:
            latestExperiment.metrics_snapshot.baseline_rmse &&
            latestExperiment.metrics_snapshot.treatment_rmse
              ? (latestExperiment.metrics_snapshot.baseline_rmse -
                  latestExperiment.metrics_snapshot.treatment_rmse) /
                Math.max(latestExperiment.metrics_snapshot.baseline_rmse, 1e-8)
              : 0,
          verdict:
            (latestExperiment.metrics_snapshot.delta?.pearson_r ?? 0) > 0
              ? 'supports'
              : 'weakens',
        }
      : undefined,
    rawHypothesisTree: hypothesisTree,
    rawDecisionLog: decisionLog,
    rawCandidateExperiments: candidateExperiments,
  }

  return {
    round,
    currentRoundNumber: currentRound,
    progressPercentage: process.progress_percentage ?? 0,
    processStage: process.current_stage ?? 'unknown',
  }
}
