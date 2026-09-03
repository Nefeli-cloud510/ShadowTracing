import type {
  EvaluationPreview,
  ExperimentPreview,
  FrontendViewModels,
  GovernanceDecisionsViewModel,
  HypothesisPreviewNode,
  KnowledgeMemoryViewModel,
  MissionViewModel,
  RoundData,
  TimelineDataBundle,
  TimelineNodeData,
  TimelineNodeStatus,
  UncertaintyPreview,
} from '../types/timeline'
import { filterSelectableCandidateExperiments, getExperimentValidationSnapshot } from '../utils/experimentValidation'

type NumericValue = number | string | { value?: number | string } | undefined

type RawTask = {
  payload?: {
    research_question?: {
      text?: string
      target?: string
      question_type?: string
      variables?: {
        x?: string
        y?: string
        m_candidates?: string[]
      }
    }
    evaluation?: {
      primary_metric?: string
      secondary_metrics?: string[]
      visual_analysis?: string[]
    }
    constraints?: Record<string, unknown>
    data_sources?: Record<string, { path?: string; time_column?: string; target_column?: string }>
  }
}

type RawProcess = {
  current_round?: number
  current_stage?: string
  current_phase?: string
  current_step?: string
  progress_percentage?: number
  user_settings?: {
    auto_continue?: boolean
  }
  user_requests?: {
    stop_requested?: boolean
  }
}

type RawHypothesisTreeNode = {
  hypothesis_id?: string
  statement?: string
  status?: string
  support_score?: number
  level?: number
  activated_at_round?: number
  created_at_round?: number
  updated_at_round?: number
  support_history?: Array<{
    round?: number
    score?: number
  }>
}

type RawHypothesisTree = {
  current_round?: number
  root_question?: string
  nodes?: RawHypothesisTreeNode[]
  tree_summary?: {
    total_nodes?: number
    active_count?: number
    pruned_count?: number
    pending_count?: number
  }
}

type RawUncertaintyRecord = {
  uncertainty_id?: string
  question?: string
  description?: string
  related_hypotheses?: string[]
  priority?: string
  resolution_status?: string
  status?: string
  resolving_experiment?: string
  created_at_round?: number
  history?: Array<{
    round?: number
    event?: string
    description?: string
  }>
}

type RawUncertainties = {
  current_round?: number
  records?: RawUncertaintyRecord[]
  priority_queue?: {
    queue?: Array<{
      uncertainty_id?: string
      question?: string
      priority_score?: number
      status?: string
      estimated_resolution_round?: number
    }>
  }
}

type RawExperimentEntry = {
  experiment_id?: string
  round_id?: number
  status?: string
  protocol_path?: string
  result_path?: string
  evaluation_path?: string
  tested_hypotheses?: string[]
  scientific_question?: string
  metrics_snapshot?: {
    experiment_id?: string
    baseline_rmse?: number
    treatment_rmse?: number
    baseline_pearson_r?: number
    treatment_pearson_r?: number
    delta?: {
      pearson_r?: number
      rmse?: number
    }
  }
  key_findings?: string[]
  visualizations?: string[]
  reasoning_traces?: Array<{
    trace_id?: string
    stage?: string
    summary?: string
    related_hypotheses?: string[]
    related_uncertainties?: string[]
  }>
}

type RawExperimentMemory = {
  current_round?: number
  entries?: RawExperimentEntry[]
}

type RawDecision = {
  decision_id?: string
  timestamp?: string
  round_id?: number
  phase?: string
  step?: string
  decision_type?: string
  made_by?: string
  summary?: string
  details?: Record<string, unknown>
}

type RawDecisionLog = {
  decisions?: RawDecision[]
  human_feedback?: Array<{
    feedback_id?: string
    timestamp?: string
    round_number?: number
    content?: string
    status?: string
    implemented_in_round?: number
  }>
  stop_history?: any[]
}

type RawCandidateExperiment = {
  experiment_id?: string
  type?: string
  scientific_question?: string
  purpose?: string
  tested_hypotheses?: string[]
  estimated_information_gain?: NumericValue
  estimated_performance_gain?: NumericValue
  estimated_risk?: NumericValue
  estimated_cost?: NumericValue
  utility_score?: NumericValue
}

type RawCandidateExperiments = {
  round?: number
  candidates?: RawCandidateExperiment[]
}

type RawPlannerInput = {
  source_round_id?: number
  next_round_id?: number
  scientific_question?: string
  evaluation_summary?: {
    experiment_id?: string
    baseline_pearson_r?: number
    treatment_pearson_r?: number
    delta_pearson_r?: number
    delta_rmse?: number
    stable?: boolean
  }
  unresolved_uncertainties?: RawUncertaintyRecord[]
  active_hypotheses?: Array<{
    hypothesis_id?: string
    statement?: string
    support_score?: number
    status?: string
  }>
  recent_hypothesis_assessments?: Array<{
    hypothesis_id?: string
    support_before?: number
    support_after?: number
    status?: string
  }>
  recent_disagreement_updates?: Array<{
    uncertainty_id?: string
    support_span_before?: number
    support_span_after?: number
    resolution_status?: string
  }>
  recent_reasoning_traces?: Array<{
    trace_id?: string
    stage?: string
    summary?: string
    related_hypotheses?: string[]
    related_uncertainties?: string[]
  }>
  recent_human_feedback?: Array<{
    content?: string
    summary?: string
  }>
  planner_guidance?: string[]
  data_dictionary_summary?: {
    dataset_name?: string
    time_column?: string
    feature_candidates?: string[]
  }
}

type RawUploadManifest = {
  records?: Array<{
    file_name?: string
    file_type?: string
    uploaded_at?: string
    extraction_status?: string
    knowledge_sync_status?: string
    knowledge_sync_note?: string
    storage_path?: string
    extracted_text_path?: string
  }>
}

type RawModelUsage = {
  session_model?: string
  routes?: Array<{
    route?: string
    model?: string
    purpose?: string
  }>
  roles?: Array<{
    role?: string
    model?: string
  }>
}

type LoaderSnapshot = {
  task: RawTask
  process: RawProcess
  decisionLog: RawDecisionLog
  hypothesisTree: RawHypothesisTree
  uncertainties: RawUncertainties
  experimentMemory: RawExperimentMemory
  candidateExperiments: RawCandidateExperiments
  plannerInput: RawPlannerInput
  plannerOutput: unknown | null
  sessionStatus?: SessionStatus | null
  uploadManifest?: RawUploadManifest
  modelUsage?: RawModelUsage
}

type SessionStatus = {
  status?: string
  stage?: string
  message?: string
  currentRound?: number
  model?: string
  updatedAt?: string
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

const PHASE_LABELS: Record<string, string> = {
  task_definition: '任务定义',
  hypothesis_generation: '假设生成',
  experiment_planning: '实验规划',
  experiment_execution: '实验执行',
  result_analysis: '结果分析',
  decision_making: '决策回写',
  next_round: '进入下一轮',
}

const STAGE_LABELS: Record<string, string> = {
  waiting_input: '等待任务录入',
  not_started: '尚未开始',
  workspace_preparing: '准备运行环境',
  awaiting_human_approval: '等待 PI 审批',
  round_running: '本轮执行中',
  round_completed: '本轮已完成',
  completed: '闭环已完成',
  failed: '运行失败',
}

const STEP_LABELS: Record<string, string> = {
  confirmation: '等待启动确认',
  step_1: '识别关键不确定性',
  step_2: '生成候选实验',
  step_3: '计算综合价值',
  step_4: '选择推荐实验',
  step_5: '生成执行协议',
}

const QUESTION_TYPE_LABELS: Record<string, string> = {
  forecasting: '预测型科学问题',
  scientific_inquiry: '科学机理追问',
}

const METRIC_LABELS: Record<string, string> = {
  Pearson_r: '相关性 Pearson r',
  RMSE: '均方根误差 RMSE',
  MAE: '平均绝对误差 MAE',
  prediction_vs_truth: '真实值与预测值对照',
  scatter_plot: '散点关系图',
}

const SOURCE_FILES = {
  task: 'task.json',
  process: 'process.json',
  hypothesisTree: 'hypothesis_tree.json',
  uncertainties: 'uncertainties.json',
  experimentMemory: 'experiment_memory.json',
  decisionLog: 'decision_log.json',
  candidateExperiments: 'candidate_experiments.json',
  plannerInput: 'planner_input.json',
  plannerOutput: 'planner_output.json',
  uploadManifest: 'upload_manifest.json',
  modelUsage: 'model_usage.json',
}

const NODE_DEFINITIONS: Array<
  Pick<TimelineNodeData, 'id' | 'shortLabel' | 'title' | 'summary' | 'relatedPage'>
> = [
  {
    id: 'Q',
    shortLabel: 'Q',
    title: '科学问题输入',
    summary: '任务定义、目标变量与约束。',
    relatedPage: 'dialogue',
  },
  {
    id: 'K',
    shortLabel: 'K',
    title: '知识注入 / RAG',
    summary: '项目资料与文献知识命中。',
    relatedPage: 'dialogue',
  },
  {
    id: 'H',
    shortLabel: 'H',
    title: '假设生成',
    summary: '竞争假设树与支持度演化。',
    relatedPage: 'hypotheses',
  },
  {
    id: 'C',
    shortLabel: 'C',
    title: '科学质询',
    summary: '质询点、分歧与关键缺口。',
    relatedPage: 'hypotheses',
  },
  {
    id: 'U',
    shortLabel: 'U',
    title: '不确定性识别',
    summary: '未解决的不确定性与优先队列。',
    relatedPage: 'uncertainties',
  },
  {
    id: 'E',
    shortLabel: 'E',
    title: '候选实验',
    summary: '候选实验与综合价值比较。',
    relatedPage: 'approval',
  },
  {
    id: 'P',
    shortLabel: 'P',
    title: 'PI 审批',
    summary: '人在环审批与实验选择。',
    relatedPage: 'approval',
  },
  {
    id: 'X',
    shortLabel: 'X',
    title: '实验执行',
    summary: '实验协议、执行状态与产物。',
    relatedPage: 'execution',
  },
  {
    id: 'A',
    shortLabel: 'A',
    title: '分析评价',
    summary: 'baseline / treatment 指标与解释。',
    relatedPage: 'execution',
  },
  {
    id: 'W',
    shortLabel: 'W',
    title: '状态回写',
    summary: '假设树、不确定性与下一轮输入回写。',
    relatedPage: 'report',
  },
]

const LOCAL_API_ORIGIN =
  typeof window !== 'undefined' && /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname)
    ? 'http://127.0.0.1:8765'
    : ''
const API_STATE_BASE =
  typeof import.meta !== 'undefined'
    ? import.meta.env.VITE_STATE_API_BASE?.trim() ?? (LOCAL_API_ORIGIN ? `${LOCAL_API_ORIGIN}/api/state` : '')
    : ''
const API_IMAGE_BASE =
  typeof import.meta !== 'undefined'
    ? import.meta.env.VITE_STATE_API_IMAGE_BASE?.trim() ?? (LOCAL_API_ORIGIN ? `${LOCAL_API_ORIGIN}/api/visualizations` : '')
    : ''
const API_SESSION_URL =
  typeof import.meta !== 'undefined'
    ? import.meta.env.VITE_WORKFLOW_API_BASE?.trim()
      ? `${import.meta.env.VITE_WORKFLOW_API_BASE.trim().replace(/\/+$/, '')}/session`
      : LOCAL_API_ORIGIN
        ? `${LOCAL_API_ORIGIN}/api/session`
        : ''
    : ''

const WORKSPACE_RESET_AT_KEY = 'shadowtracing.workspaceResetAt'

type StateSource = {
  mode: 'api'
  baseUrl: string
}

function joinSourcePath(baseUrl: string, fileName: string): string {
  const normalizedBase = baseUrl.replace(/\/+$/, '')
  return `${normalizedBase}/${fileName}`
}

function readWorkspaceResetAt(): string | null {
  if (typeof window === 'undefined') {
    return null
  }
  return window.localStorage.getItem(WORKSPACE_RESET_AT_KEY)
}

async function readJsonText(path: string): Promise<string | null> {
  const response = await fetch(path)
  if (!response.ok) {
    return null
  }

  const text = await response.text()
  const trimmed = text.trim()

  if (!trimmed) {
    return null
  }

  if (/^<!doctype html/i.test(trimmed) || /^<html/i.test(trimmed) || trimmed.startsWith('<')) {
    return null
  }

  return trimmed
}

async function readSessionStatus(): Promise<SessionStatus | null> {
  if (!API_SESSION_URL) {
    return null
  }

  const text = await readJsonText(API_SESSION_URL)
  if (!text) {
    return null
  }

  try {
    return JSON.parse(text) as SessionStatus
  } catch {
    return null
  }
}

function isSnapshotStaleAfterReset(snapshot: LoaderSnapshot, session: SessionStatus | null): boolean {
  const resetAt = readWorkspaceResetAt()
  if (!resetAt) {
    return false
  }
  const taskCreatedAt = snapshot.task?.payload?.research_question?.text ? (snapshot.task as RawTask & { created_at?: string }).created_at : undefined
  const snapshotMarkers = [taskCreatedAt, session?.updatedAt].filter((value): value is string => Boolean(value))
  if (snapshotMarkers.length === 0) {
    return true
  }
  return snapshotMarkers.every((value) => value <= resetAt)
}

async function readJson<T>(path: string): Promise<T> {
  const text = await readJsonText(path)
  if (!text) {
    throw new Error(`状态数据读取失败：${path}`)
  }

  try {
    return JSON.parse(text) as T
  } catch (error) {
    throw new Error(
      `状态数据解析失败：${error instanceof Error ? error.message : 'parse failed'}`,
    )
  }
}

async function readJsonOptional<T>(path: string): Promise<T | null> {
  const text = await readJsonText(path)
  if (!text) {
    return null
  }

  try {
    return JSON.parse(text) as T
  } catch {
    return null
  }
}

function getStateSources(): StateSource[] {
  if (!API_STATE_BASE) {
    return []
  }

  return [
    {
      mode: 'api',
      baseUrl: API_STATE_BASE,
    },
  ]
}

function createEmptySnapshot(session?: SessionStatus | null): LoaderSnapshot {
  return {
    task: {} as RawTask,
    process: {
      current_round: Number(session?.currentRound ?? 0),
      current_stage: session?.stage ?? 'waiting_input',
      current_phase: 'task_definition',
      current_step: 'confirmation',
      progress_percentage: session?.status === 'starting' ? 5 : 0,
      user_settings: {
        auto_continue: false,
      },
      user_requests: {
        stop_requested: false,
      },
    } as RawProcess,
    decisionLog: {
      decisions: [],
      human_feedback: [],
      stop_history: [],
    } as RawDecisionLog,
    hypothesisTree: {
      current_round: 0,
      root_question: '',
      nodes: [],
      tree_summary: {
        total_nodes: 0,
        active_count: 0,
        pruned_count: 0,
        pending_count: 0,
      },
    } as RawHypothesisTree,
    uncertainties: {
      current_round: 0,
      records: [],
      priority_queue: {
        queue: [],
      },
    } as RawUncertainties,
    experimentMemory: {
      current_round: 0,
      entries: [],
    } as RawExperimentMemory,
    candidateExperiments: {
      round: 0,
      candidates: [],
    } as RawCandidateExperiments,
    plannerInput: {} as RawPlannerInput,
    plannerOutput: null,
  }
}

function normalizeWhitespace(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

function truncateText(text: string, maxLength = 180): string {
  if (text.length <= maxLength) {
    return text
  }
  return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`
}

function humanizeCode(value: string | undefined, fallback: string): string {
  if (!value) {
    return fallback
  }

  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function sanitizeText(value: unknown, maxLength = 180): string {
  if (typeof value !== 'string') {
    return ''
  }

  let text = normalizeWhitespace(value)
  const suspiciousMarkers = [
    '{\\"',
    '\\"}',
    '\\"uncertainty_id',
    'recent_reasoning_traces',
    'priority\\":',
    'ort_span_after',
  ]

  for (const marker of suspiciousMarkers) {
    const index = text.indexOf(marker)
    if (index > 24) {
      text = text.slice(0, index).trim()
    }
  }

  text = text.replace(/^rag_(project|literature|external):/i, '').trim()
  return truncateText(text, maxLength)
}

function getVisualizationLabel(path: string): string {
  const fileName = path.split('/').pop() ?? path
  return fileName.replace(/\.(png|jpg|jpeg|webp)$/i, '').replace(/_/g, ' ')
}

function getVisualizationPreviewUrl(path: string): string {
  const normalizedPath = path.replace(/^\/+/, '')
  if (API_IMAGE_BASE) {
    return `${API_IMAGE_BASE.replace(/\/+$/, '')}/${normalizedPath}`
  }
  return normalizedPath
}

function candidateMetrics(item?: RawCandidateExperiment) {
  return {
    informationGain: toNumber(item?.estimated_information_gain),
    performanceGain: toNumber(item?.estimated_performance_gain),
    risk: toNumber(item?.estimated_risk),
    cost: toNumber(item?.estimated_cost),
    utility: toNumber(item?.utility_score),
  }
}

function uniqueStrings(values: unknown[], maxLength = 180): string[] {
  const seen = new Set<string>()
  const result: string[] = []

  for (const value of values) {
    const text = sanitizeText(value, maxLength)
    if (!text) {
      continue
    }
    const key = text.toLowerCase()
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    result.push(text)
  }

  return result
}

function getSelectableCandidates(snapshot: LoaderSnapshot): RawCandidateExperiment[] {
  return filterSelectableCandidateExperiments([...(snapshot.candidateExperiments.candidates ?? [])])
}

function toNumber(value: NumericValue): number {
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

function getQuestionText(task: RawTask, plannerInput: RawPlannerInput): string {
  return sanitizeText(task.payload?.research_question?.text ?? plannerInput.scientific_question ?? '', 320)
}

function humanizePhase(phase?: string): string {
  return PHASE_LABELS[phase ?? ''] ?? humanizeCode(phase, '未开始')
}

function humanizeStage(stage?: string): string {
  return STAGE_LABELS[stage ?? ''] ?? humanizeCode(stage, '状态待更新')
}

function humanizeStep(step?: string): string {
  return STEP_LABELS[step ?? ''] ?? humanizeCode(step, '等待推进')
}

function humanizeQuestionType(type?: string): string {
  return QUESTION_TYPE_LABELS[type ?? ''] ?? humanizeCode(type, '待识别问题类型')
}

function humanizeMetric(metric?: string): string {
  return METRIC_LABELS[metric ?? ''] ?? sanitizeText(metric ?? '', 80)
}

function summarizePath(path?: string): string {
  if (!path) {
    return '未提供'
  }

  const normalized = path.replace(/\\/g, '/')
  return normalized.split('/').pop() ?? path
}

function formatModelScope(scope: string): string {
  const mapping: Record<string, string> = {
    session: '会话默认模型',
    '/api/session/analyze-question': '问题解析接口',
    '/api/workflow/start': '会话启动接口',
    hypothesis_proposer: '假设提出者',
    scientific_questioner: '科学质询者',
    central_controller: '中央控制者',
    experiment_planner: '实验规划者',
    scientific_interpreter: '科学解释者',
  }
  return mapping[scope] ?? humanizeCode(scope, scope)
}

function formatConstraintEntry(key: string, value: unknown): string {
  const normalizedKey = key.trim()

  if (normalizedKey === 'no_future_information') {
    return `严格避免未来信息泄露：${value ? '是' : '否'}`
  }
  if (normalizedKey === 'validation_feedback_allowed') {
    return `允许基于验证结果迭代：${value ? '是' : '否'}`
  }
  if (normalizedKey === 'max_rounds') {
    return `最大闭环轮数：${String(value)}`
  }
  if (normalizedKey === 'resource_budget' && value && typeof value === 'object') {
    const budget = value as Record<string, unknown>
    return `资源预算：token ${String(budget.token_budget ?? '--')} / 单轮时限 ${String(
      budget.max_time_seconds_per_round ?? '--',
    )} 秒`
  }

  return `${humanizeCode(normalizedKey, normalizedKey)}：${String(value)}`
}

function formatBudgetLabel(label: string): string {
  if (label === 'token_budget') {
    return '推理预算'
  }
  if (label === 'max_time_seconds_per_round') {
    return '单轮时限（秒）'
  }
  return humanizeCode(label, label)
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

function priorityToLevel(priority?: string): UncertaintyPreview['priority'] {
  if (priority === 'high') return 'P1'
  if (priority === 'medium') return 'P2'
  return 'P3'
}

function priorityScore(priority?: string): number {
  if (priority === 'high') return 0.9
  if (priority === 'medium') return 0.6
  return 0.3
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

function supportScoreAtRound(node: RawHypothesisTreeNode, roundNumber: number): number {
  const history = [...(node.support_history ?? [])]
    .filter((item) => (item.round ?? 0) <= roundNumber)
    .sort((a, b) => (b.round ?? 0) - (a.round ?? 0))

  return history[0]?.score ?? node.support_score ?? 0
}

function hypothesisStatusAtRound(
  node: RawHypothesisTreeNode,
  roundNumber: number,
  currentRound: number,
): HypothesisPreviewNode['status'] {
  const activatedAtRound = node.activated_at_round ?? 0
  if (roundNumber === currentRound && activatedAtRound === currentRound) {
    return 'newly_split'
  }

  return mapHypothesisStatus(node.status)
}

function computePgActual(metricsSnapshot: RawExperimentEntry['metrics_snapshot']): number {
  const baseline = metricsSnapshot?.baseline_rmse
  const treatment = metricsSnapshot?.treatment_rmse
  if (!baseline || !treatment) {
    return 0
  }

  return (baseline - treatment) / Math.max(baseline, 1e-8)
}

function inferVerdict(deltaPearsonR?: number): EvaluationPreview['verdict'] {
  const delta = deltaPearsonR ?? 0
  if (delta > 0.005) {
    return 'supports'
  }
  if (delta < -0.005) {
    return 'weakens'
  }
  return 'mixed'
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

  if (process.user_requests?.stop_requested) {
    return 'paused'
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

function nodeStatusForRound(
  nodeId: string,
  roundNumber: number,
  currentRound: number,
  process: RawProcess,
): TimelineNodeStatus {
  if (roundNumber < currentRound) {
    return 'completed'
  }
  if (roundNumber > currentRound) {
    return 'pending'
  }
  return nodeStatusFromProcess(nodeId, process)
}

function collectRoundNumbers(snapshot: LoaderSnapshot): number[] {
  const rounds = new Set<number>()
  const addRound = (value: unknown) => {
    const numeric = Number(value)
    if (Number.isFinite(numeric) && numeric > 0) {
      rounds.add(numeric)
    }
  }

  addRound(snapshot.process.current_round)
  addRound(snapshot.candidateExperiments.round)
  addRound(snapshot.hypothesisTree.current_round)
  addRound(snapshot.uncertainties.current_round)
  addRound(snapshot.experimentMemory.current_round)
  addRound(snapshot.plannerInput.source_round_id)
  addRound(snapshot.plannerInput.next_round_id)

  for (const entry of snapshot.experimentMemory.entries ?? []) {
    addRound(entry.round_id)
  }

  for (const decision of snapshot.decisionLog.decisions ?? []) {
    addRound(decision.round_id)
  }

  for (const feedback of snapshot.decisionLog.human_feedback ?? []) {
    addRound(feedback.round_number)
    addRound(feedback.implemented_in_round)
  }

  for (const node of snapshot.hypothesisTree.nodes ?? []) {
    addRound(node.activated_at_round)
    addRound(node.created_at_round)
    addRound(node.updated_at_round)
    for (const history of node.support_history ?? []) {
      addRound(history.round)
    }
  }

  for (const record of snapshot.uncertainties.records ?? []) {
    addRound(record.created_at_round)
    for (const history of record.history ?? []) {
      addRound(history.round)
    }
  }

  for (const item of snapshot.uncertainties.priority_queue?.queue ?? []) {
    addRound(item.estimated_resolution_round)
  }

  return [...rounds].sort((a, b) => a - b)
}

function inferCurrentRound(rounds: number[], snapshot: LoaderSnapshot): number {
  const explicitCandidates = [
    snapshot.candidateExperiments.round,
    snapshot.hypothesisTree.current_round,
    snapshot.uncertainties.current_round,
    snapshot.plannerInput.next_round_id,
  ]
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value > 0)

  if (explicitCandidates.length > 0) {
    return Math.max(...explicitCandidates)
  }

  return rounds.length > 0 ? Math.max(...rounds) : 0
}

function buildHypothesisPreviews(
  roundNumber: number,
  currentRound: number,
  hypothesisTree: RawHypothesisTree,
): HypothesisPreviewNode[] {
  return (hypothesisTree.nodes ?? [])
    .filter((item) => (item.activated_at_round ?? 0) <= roundNumber)
    .sort((a, b) => supportScoreAtRound(b, roundNumber) - supportScoreAtRound(a, roundNumber))
    .slice(0, roundNumber === currentRound ? 4 : 3)
    .map((item, index) => ({
      id: item.hypothesis_id ?? `H${index + 1}`,
      label: sanitizeText(item.statement ?? '未命名假设', 96),
      status: hypothesisStatusAtRound(item, roundNumber, currentRound),
      supportScore: supportScoreAtRound(item, roundNumber),
      level: item.level,
    }))
}

function buildUncertaintyPreviews(
  roundNumber: number,
  currentRound: number,
  uncertainties: RawUncertainties,
  plannerInput: RawPlannerInput,
  maxItems = roundNumber === currentRound ? 2 : 1,
): UncertaintyPreview[] {
  const queueOrder = new Map<string, number>()
  for (const item of uncertainties.priority_queue?.queue ?? []) {
    if (item.uncertainty_id) {
      queueOrder.set(item.uncertainty_id, item.priority_score ?? 0)
    }
  }

  const candidates = [
    ...(uncertainties.records ?? []).filter((item) => (item.created_at_round ?? 0) <= roundNumber),
    ...((roundNumber === currentRound ? plannerInput.unresolved_uncertainties : []) ?? []),
  ]

  const uniqueMap = new Map<string, RawUncertaintyRecord>()
  for (const item of candidates) {
    const id = item.uncertainty_id
    if (!id) {
      continue
    }
    if (!uniqueMap.has(id)) {
      uniqueMap.set(id, item)
    }
  }

  return [...uniqueMap.values()]
    .sort((a, b) => {
      const queueDiff = (queueOrder.get(b.uncertainty_id ?? '') ?? priorityScore(b.priority)) -
        (queueOrder.get(a.uncertainty_id ?? '') ?? priorityScore(a.priority))
      if (queueDiff !== 0) {
        return queueDiff
      }
      return priorityScore(b.priority) - priorityScore(a.priority)
    })
    .slice(0, maxItems)
    .map((item, index) => ({
      id: item.uncertainty_id ?? `U${index + 1}`,
      title: sanitizeText(item.question ?? item.description ?? '未命名不确定性', 116),
      priority: priorityToLevel(item.priority),
      resolutionStatus: mapResolutionStatus(item.resolution_status),
      relatedHypotheses: item.related_hypotheses ?? [],
    }))
}

function buildExperimentPreviews(
  roundNumber: number,
  currentRound: number,
  candidateExperiments: RawCandidateExperiments,
  experimentMemory: RawExperimentMemory,
): ExperimentPreview[] {
  const selectableCandidates = filterSelectableCandidateExperiments([...(candidateExperiments.candidates ?? [])])
  if (roundNumber === currentRound && (candidateExperiments.round ?? currentRound) >= roundNumber) {
    return selectableCandidates
      .sort((a, b) => toNumber(b.utility_score) - toNumber(a.utility_score))
      .slice(0, 3)
      .map((item, index) => ({
        id: item.experiment_id ?? `E_${index + 1}`,
        targetHypothesis: item.tested_hypotheses?.[0] ?? 'unknown',
        utility: toNumber(item.utility_score),
        informationGain: toNumber(item.estimated_information_gain),
        performanceGain: toNumber(item.estimated_performance_gain),
        status: index === 0 ? 'recommended' : 'candidate',
        scientificQuestion: sanitizeText(item.scientific_question ?? item.purpose, 160),
      }))
  }

  return (experimentMemory.entries ?? [])
    .filter((entry) => (entry.round_id ?? 0) === roundNumber)
    .slice(0, 3)
    .map((entry) => ({
      id: entry.experiment_id ?? `E_R${roundNumber}_00`,
      targetHypothesis: entry.tested_hypotheses?.[0] ?? 'executed',
      utility: 0,
      informationGain: 0,
      performanceGain: entry.metrics_snapshot?.delta?.pearson_r ?? 0,
      status: 'completed',
      scientificQuestion: sanitizeText(entry.scientific_question ?? entry.key_findings?.[0], 160),
    }))
}

function buildEvaluationPreview(
  roundNumber: number,
  experimentMemory: RawExperimentMemory,
  plannerInput: RawPlannerInput,
): EvaluationPreview | undefined {
  const roundEntry = [...(experimentMemory.entries ?? [])]
    .filter((entry) => (entry.round_id ?? 0) === roundNumber)
    .sort((a, b) => (b.round_id ?? 0) - (a.round_id ?? 0))[0]

  if (roundEntry?.metrics_snapshot) {
    return {
      experimentId: roundEntry.metrics_snapshot.experiment_id ?? roundEntry.experiment_id,
      baselinePearsonR: roundEntry.metrics_snapshot.baseline_pearson_r ?? 0,
      treatmentPearsonR: roundEntry.metrics_snapshot.treatment_pearson_r ?? 0,
      deltaPearsonR: roundEntry.metrics_snapshot.delta?.pearson_r ?? 0,
      deltaRmse: roundEntry.metrics_snapshot.delta?.rmse ?? 0,
      pgActual: computePgActual(roundEntry.metrics_snapshot),
      verdict: inferVerdict(roundEntry.metrics_snapshot.delta?.pearson_r),
      stable: plannerInput.evaluation_summary?.stable,
    }
  }

  return undefined
}

function collectRagSummaries(plannerInput: RawPlannerInput): KnowledgeMemoryViewModel['ragSummaries'] {
  const guidance = plannerInput.planner_guidance ?? []
  const traces = plannerInput.recent_reasoning_traces ?? []

  return {
    project: uniqueStrings(
      [
        ...guidance.filter((item) => item.startsWith('rag_project:')),
        ...traces
          .filter((item) => item.stage === 'rag_project')
          .map((item) => item.summary ?? ''),
      ],
      180,
    ),
    literature: uniqueStrings(
      [
        ...guidance.filter((item) => item.startsWith('rag_literature:')),
        ...traces
          .filter((item) => item.stage === 'rag_literature')
          .map((item) => item.summary ?? ''),
      ],
      180,
    ),
    external: uniqueStrings(
      [
        ...guidance.filter((item) => item.startsWith('rag_external:')),
        ...traces
          .filter((item) => item.stage === 'rag_external')
          .map((item) => item.summary ?? ''),
      ],
      180,
    ),
  }
}

function buildNodeDetails(
  nodeId: string,
  roundNumber: number,
  currentRound: number,
  snapshot: LoaderSnapshot,
  roundHypotheses: HypothesisPreviewNode[],
  roundUncertainties: UncertaintyPreview[],
  roundExperiments: ExperimentPreview[],
  evaluation: EvaluationPreview | undefined,
): string[] {
  const currentRoundDecisions = (snapshot.decisionLog.decisions ?? [])
    .filter((item) => (item.round_id ?? currentRound) === roundNumber)
    .sort((a, b) => (a.timestamp ?? '').localeCompare(b.timestamp ?? ''))
  const roundEntry = [...(snapshot.experimentMemory.entries ?? [])]
    .filter((entry) => (entry.round_id ?? 0) === roundNumber)
    .sort((a, b) => (b.round_id ?? 0) - (a.round_id ?? 0))[0]
  const ragSummaries = collectRagSummaries(snapshot.plannerInput)

  switch (nodeId) {
    case 'Q':
      return [
        sanitizeText(snapshot.task.payload?.research_question?.text ?? '暂无科学问题', 96),
        `目标变量：${snapshot.task.payload?.research_question?.target ?? '未定义'}`,
      ]
    case 'K':
      return uniqueStrings(
        [
          ...ragSummaries.project.slice(0, 1),
          ...ragSummaries.literature.slice(0, 1),
          `承接自第 ${snapshot.plannerInput.source_round_id ?? Math.max(1, roundNumber - 1)} 轮规划`,
        ],
        96,
      ).slice(0, 2)
    case 'H':
      return roundHypotheses.map((node) => `${node.id} · ${node.supportScore.toFixed(3)}`)
    case 'C':
      return uniqueStrings(
        [
          ...currentRoundDecisions
            .filter(
              (item) =>
                item.decision_type?.includes('scientific_interpreter') ||
                item.decision_type?.includes('planner_output'),
            )
            .map((item) => `${item.made_by ?? 'system'} · ${item.summary ?? ''}`),
          ...(snapshot.plannerInput.recent_reasoning_traces ?? [])
            .filter((item) => item.stage === 'scientific_questioner')
            .map((item) => item.summary ?? ''),
        ],
        96,
      ).slice(0, 3)
    case 'U':
      return roundUncertainties.map((item) => `${item.id} · ${item.title}`)
    case 'E':
      return roundExperiments.map((item) => `${item.id} · U(E) ${item.utility.toFixed(3)}`)
    case 'P':
      return uniqueStrings(
        currentRoundDecisions
          .filter(
            (item) =>
              item.decision_type?.includes('experiment') || item.decision_type?.includes('round'),
          )
          .map((item) => `${item.decision_type} · ${item.summary ?? ''}`),
        96,
      ).slice(0, 3)
    case 'X':
      return roundEntry
        ? [
            `实验编号：${roundEntry.experiment_id ?? '未命名实验'}`,
            `执行状态：${humanizeStage(roundEntry.status)}`,
            roundEntry.visualizations?.length ? `已生成 ${roundEntry.visualizations.length} 份可视化产物` : '等待生成可视化产物',
          ]
        : ['当前轮尚未执行实验']
    case 'A':
      return evaluation
        ? [
            `基线相关性：${(evaluation.baselinePearsonR ?? 0).toFixed(4)}`,
            `实验后相关性：${(evaluation.treatmentPearsonR ?? 0).toFixed(4)}`,
            `改善幅度：${evaluation.deltaPearsonR.toFixed(4)}`,
          ]
        : ['暂无评价结果']
    case 'W':
      return uniqueStrings(
        [
          `当前阶段：${humanizePhase(snapshot.process.current_phase)}`,
          `下一轮：${snapshot.plannerInput.next_round_id ?? '未生成'}`,
          ...(roundNumber === currentRound
            ? (snapshot.plannerInput.recent_disagreement_updates ?? []).map(
                (item) =>
                  `${item.uncertainty_id} · 分歧跨度 ${Number(item.support_span_before ?? 0).toFixed(3)} -> ${Number(
                    item.support_span_after ?? 0,
                  ).toFixed(3)}`,
              )
            : []),
        ],
        96,
      ).slice(0, 3)
    default:
      return []
  }
}

function buildTimelineNodesForRound(
  roundNumber: number,
  currentRound: number,
  snapshot: LoaderSnapshot,
  roundHypotheses: HypothesisPreviewNode[],
  roundUncertainties: UncertaintyPreview[],
  roundExperiments: ExperimentPreview[],
  evaluation: EvaluationPreview | undefined,
): TimelineNodeData[] {
  return NODE_DEFINITIONS.map((node) => ({
    ...node,
    status: nodeStatusForRound(node.id, roundNumber, currentRound, snapshot.process),
    detailItems: buildNodeDetails(
      node.id,
      roundNumber,
      currentRound,
      snapshot,
      roundHypotheses,
      roundUncertainties,
      roundExperiments,
      evaluation,
    ),
  }))
}

function buildRoundData(
  roundNumber: number,
  currentRound: number,
  snapshot: LoaderSnapshot,
): RoundData {
  const hypotheses = buildHypothesisPreviews(roundNumber, currentRound, snapshot.hypothesisTree)
  const uncertainties = buildUncertaintyPreviews(
    roundNumber,
    currentRound,
    snapshot.uncertainties,
    snapshot.plannerInput,
  )
  const experiments = buildExperimentPreviews(
    roundNumber,
    currentRound,
    snapshot.candidateExperiments,
    snapshot.experimentMemory,
  )
  const evaluation = buildEvaluationPreview(roundNumber, snapshot.experimentMemory, snapshot.plannerInput)

  return {
    id: `round-${roundNumber}`,
    roundNumber,
    title: `第 ${roundNumber} 轮`,
    subtitle: roundNumber === currentRound ? humanizePhase(snapshot.process.current_phase) : '本轮已归档',
    stateLabel: roundNumber === currentRound ? humanizeStage(snapshot.process.current_stage) : '已归档',
    questionSummary: getQuestionText(snapshot.task, snapshot.plannerInput),
    isCurrent: roundNumber === currentRound,
    isCollapsed: roundNumber !== currentRound,
    nodes: buildTimelineNodesForRound(
      roundNumber,
      currentRound,
      snapshot,
      hypotheses,
      uncertainties,
      experiments,
      evaluation,
    ),
    hypotheses,
    uncertainties,
    experiments,
    evaluation,
  }
}

function buildMissionViewModel(snapshot: LoaderSnapshot): MissionViewModel {
  const constraints = (snapshot.task.payload?.constraints ?? {}) as Record<string, unknown>
  const evaluation = snapshot.task.payload?.evaluation ?? {}
  const dataSources = (snapshot.task.payload?.data_sources ?? {}) as Record<
    string,
    { path?: string; time_column?: string; target_column?: string }
  >

  const guidance = uniqueStrings(
    [
      ...(snapshot.decisionLog.human_feedback ?? []).map((item) => item.content ?? ''),
      ...(snapshot.decisionLog.decisions ?? []).map((item) => item.details?.human_feedback),
    ],
    220,
  )
  const dialogueMessages = [
    {
      id: 'system-status',
      role: 'system' as const,
      speaker: '系统',
      content: `当前处于${humanizePhase(snapshot.process.current_phase)}，整体状态为${humanizeStage(snapshot.process.current_stage)}。`,
      timestamp: undefined,
    },
    ...(snapshot.decisionLog.decisions ?? []).map((item, index) => ({
      id: item.decision_id ?? `decision-${index + 1}`,
      role:
        item.made_by === 'human_pi'
          ? ('user' as const)
          : item.made_by?.includes('controller')
            ? ('agent' as const)
            : ('system' as const),
      speaker:
        item.made_by === 'human_pi'
          ? 'PI'
          : item.made_by === 'central_controller'
            ? '中央进程控制者'
            : item.made_by ?? '系统',
      content: sanitizeText(item.summary ?? '', 180),
      timestamp: item.timestamp,
    })),
    ...(snapshot.decisionLog.human_feedback ?? []).map((item, index) => ({
      id: item.feedback_id ?? `feedback-${index + 1}`,
      role: 'user' as const,
      speaker: 'PI',
      content: sanitizeText(item.content ?? '', 180),
      timestamp: item.timestamp,
    })),
  ]
    .filter((item) => item.content)
    .sort((a, b) => (a.timestamp ?? '').localeCompare(b.timestamp ?? ''))
    .slice(-8)

  const expertStates: MissionViewModel['expertStates'] = [
    {
      id: 'central-controller',
      label: '中央进程控制者',
      status: 'active',
      summary: `正在调度${humanizePhase(snapshot.process.current_phase)}，当前推进到${humanizeStep(snapshot.process.current_step)}`,
    },
    {
      id: 'hypothesis-proposer',
      label: '假设提出者',
      status: (snapshot.plannerInput.active_hypotheses?.length ?? 0) > 0 ? 'completed' : 'waiting',
      summary: `${snapshot.plannerInput.active_hypotheses?.length ?? 0} 个活跃假设`,
    },
    {
      id: 'scientific-questioner',
      label: '科学质询者',
      status: (snapshot.plannerInput.unresolved_uncertainties?.length ?? 0) > 0 ? 'completed' : 'waiting',
      summary: `${snapshot.plannerInput.unresolved_uncertainties?.length ?? 0} 个关键不确定性`,
    },
    {
      id: 'experiment-planner',
      label: '实验规划者',
      status:
        snapshot.process.current_phase === 'experiment_planning'
          ? 'running'
          : getSelectableCandidates(snapshot).length > 0
            ? 'completed'
            : 'waiting',
      summary: `${getSelectableCandidates(snapshot).length} 个候选实验`,
    },
    {
      id: 'scientific-interpreter',
      label: '科学解释者',
      status:
        snapshot.process.current_phase === 'result_analysis'
          ? 'running'
          : snapshot.plannerInput.evaluation_summary
            ? 'completed'
            : 'waiting',
      summary: snapshot.plannerInput.evaluation_summary?.experiment_id
        ? `解释 ${snapshot.plannerInput.evaluation_summary.experiment_id}`
        : '等待实验结果',
    },
  ]

  return {
    scientificQuestion: getQuestionText(snapshot.task, snapshot.plannerInput),
    target: snapshot.task.payload?.research_question?.target ?? '未定义',
    questionType: humanizeQuestionType(snapshot.task.payload?.research_question?.question_type),
    variables: {
      x: snapshot.task.payload?.research_question?.variables?.x,
      y: snapshot.task.payload?.research_question?.variables?.y,
      mCandidates: snapshot.task.payload?.research_question?.variables?.m_candidates ?? [],
    },
    constraints: uniqueStrings(
      Object.entries(constraints).map(([key, value]) => formatConstraintEntry(key, value)),
      160,
    ),
    metrics: uniqueStrings(
      [
        humanizeMetric(evaluation.primary_metric),
        ...(evaluation.secondary_metrics ?? []).map((item) => humanizeMetric(item)),
        ...(evaluation.visual_analysis ?? []).map((item) => humanizeMetric(item)),
      ],
      80,
    ),
    dataSources: Object.entries(dataSources).map(([id, item]) => ({
      id,
        path: summarizePath(item.path),
      timeColumn: item.time_column,
      targetColumn: item.target_column,
    })),
    piGuidance: guidance.map((content, index) => ({
      id: `guidance-${index + 1}`,
      content,
      source: index === 0 ? 'human_feedback' : 'decision_log',
    })),
    dialogueMessages,
    expertStates,
  }
}

function buildKnowledgeMemoryViewModel(snapshot: LoaderSnapshot): KnowledgeMemoryViewModel {
  const ragSummaries = collectRagSummaries(snapshot.plannerInput)
  const currentRound = inferCurrentRound(collectRoundNumbers(snapshot), snapshot)

  return {
    rootQuestion: sanitizeText(
      snapshot.hypothesisTree.root_question ?? getQuestionText(snapshot.task, snapshot.plannerInput),
      320,
    ),
    treeSummary: {
      totalNodes: snapshot.hypothesisTree.tree_summary?.total_nodes ?? (snapshot.hypothesisTree.nodes ?? []).length,
      activeCount: snapshot.hypothesisTree.tree_summary?.active_count ?? 0,
      prunedCount: snapshot.hypothesisTree.tree_summary?.pruned_count ?? 0,
      pendingCount: snapshot.hypothesisTree.tree_summary?.pending_count ?? 0,
    },
    highlightedHypotheses: buildHypothesisPreviews(currentRound, currentRound, snapshot.hypothesisTree),
    allHypotheses: snapshot.hypothesisTree.nodes ?? [],
    uncertaintyQueue: (snapshot.uncertainties.priority_queue?.queue ?? []).map((item) => ({
      id: item.uncertainty_id ?? 'unknown',
      question: sanitizeText(item.question ?? '', 180),
      priorityScore: Number(item.priority_score ?? 0),
      status: item.status ?? 'unknown',
      estimatedResolutionRound: item.estimated_resolution_round,
    })),
    uncertaintyRecords: [...(snapshot.uncertainties.records ?? [])].sort(
      (a, b) => priorityScore(b.priority) - priorityScore(a.priority),
    ),
    experimentEntries: [...(snapshot.experimentMemory.entries ?? [])].sort(
      (a, b) => (b.round_id ?? 0) - (a.round_id ?? 0),
    ),
    ragSummaries,
  }
}

function buildExperimentEvaluationViewModel(
  snapshot: LoaderSnapshot,
  currentRound: number,
): FrontendViewModels['experimentEvaluation'] {
  const candidateExperiments = [...(snapshot.candidateExperiments.candidates ?? [])]
    .filter((item) => filterSelectableCandidateExperiments([item]).length > 0)
    .sort((a, b) => toNumber(b.utility_score) - toNumber(a.utility_score))
    .map((item) => ({
      ...item,
      scientific_question: sanitizeText(item.scientific_question ?? item.purpose, 220),
      purpose: sanitizeText(item.purpose ?? item.scientific_question, 220),
    }))

  const experimentEntries = [...(snapshot.experimentMemory.entries ?? [])].sort(
    (a, b) => (b.round_id ?? 0) - (a.round_id ?? 0),
  )
  const latestEntry = experimentEntries[0]
  const latestProtocolDecision = [...(snapshot.decisionLog.decisions ?? [])]
    .reverse()
    .find((item) => item.decision_type === 'protocol_generated')

  return {
    recommendedExperimentId: candidateExperiments[0]?.experiment_id,
    executionPlanSummary: sanitizeText(
      String(
        latestProtocolDecision?.details?.plan_summary
          ?? latestProtocolDecision?.details?.scientific_objective
          ?? '',
      ),
      320,
    ) || undefined,
    candidateExperiments,
    experimentEntries,
    latestEvaluation: buildEvaluationPreview(currentRound - 1, snapshot.experimentMemory, snapshot.plannerInput)
      ?? buildEvaluationPreview(currentRound, snapshot.experimentMemory, snapshot.plannerInput),
    metricComparison: latestEntry?.metrics_snapshot
      ? {
          baselineRmse: latestEntry.metrics_snapshot.baseline_rmse,
          treatmentRmse: latestEntry.metrics_snapshot.treatment_rmse,
          baselinePearsonR: latestEntry.metrics_snapshot.baseline_pearson_r,
          treatmentPearsonR: latestEntry.metrics_snapshot.treatment_pearson_r,
          deltaPearsonR: latestEntry.metrics_snapshot.delta?.pearson_r,
          deltaRmse: latestEntry.metrics_snapshot.delta?.rmse,
        }
      : undefined,
    visualizationPaths: latestEntry?.visualizations ?? [],
    visualizationItems: (latestEntry?.visualizations ?? []).map((item) => ({
      path: item,
      label: getVisualizationLabel(item),
      previewUrl: getVisualizationPreviewUrl(item),
      variant: item.includes('/baseline/')
        ? 'baseline'
        : item.includes('/treatment/')
          ? 'treatment'
          : 'artifact',
    })),
  }
}

function buildGovernanceViewModel(
  snapshot: LoaderSnapshot,
  currentRound: number,
): GovernanceDecisionsViewModel {
  const decisions = [...(snapshot.decisionLog.decisions ?? [])].sort((a, b) =>
    `${a.round_id ?? 0}-${a.timestamp ?? ''}`.localeCompare(`${b.round_id ?? 0}-${b.timestamp ?? ''}`),
  )
  const requestByRound = new Map<number, RawDecision>()
  const approvalByRound = new Map<number, RawDecision>()
  const reviewByRound = new Map<number, RawDecision>()
  const candidateById = new Map<string, RawCandidateExperiment>()

  for (const candidate of getSelectableCandidates(snapshot)) {
    if (candidate.experiment_id) {
      candidateById.set(candidate.experiment_id, candidate)
    }
  }

  for (const decision of decisions) {
    const roundNumber = decision.round_id ?? 0
    if (decision.decision_type === 'experiment_selection_requested') {
      requestByRound.set(roundNumber, decision)
    }
    if (decision.decision_type === 'experiment_approved') {
      approvalByRound.set(roundNumber, decision)
    }
    if (decision.decision_type === 'round_review_requested') {
      reviewByRound.set(roundNumber, decision)
    }
  }

  const pendingApproval = [...decisions]
    .reverse()
    .find(
      (item) =>
        (item.round_id ?? currentRound) === currentRound &&
        item.decision_type?.includes('requested'),
    )

  return {
    processSummary: {
      currentPhase: humanizePhase(snapshot.process.current_phase),
      currentStage: humanizeStage(snapshot.process.current_stage),
      currentStep: humanizeStep(snapshot.process.current_step),
      autoContinue: Boolean(snapshot.process.user_settings?.auto_continue),
      stopRequested: Boolean(snapshot.process.user_requests?.stop_requested),
    },
    pendingApproval: pendingApproval
      ? {
          candidateId: String(pendingApproval.details?.candidate_id ?? ''),
          utilityScore: toNumber(pendingApproval.details?.utility_score as NumericValue),
          summary: sanitizeText(pendingApproval.summary ?? '等待审批', 180),
        }
      : undefined,
    approvals: decisions.filter(
      (item) =>
        item.made_by === 'human_pi' ||
        item.decision_type?.includes('approved') ||
        item.decision_type?.includes('continue_next_round') ||
        item.decision_type?.includes('round_adjusted'),
    ),
    roundReviews: decisions.filter((item) => item.decision_type?.includes('round_')),
    auditTrail: decisions.filter(
      (item) =>
        item.decision_type?.includes('planner_input') ||
        item.decision_type?.includes('planner_output') ||
        item.decision_type?.includes('protocol_generated'),
    ),
    approvalComparisons: [...new Set([
      ...requestByRound.keys(),
      ...approvalByRound.keys(),
      ...reviewByRound.keys(),
    ])]
      .sort((a, b) => a - b)
      .map((roundNumber) => {
        const requestedDecision = requestByRound.get(roundNumber)
        const approvedDecision = approvalByRound.get(roundNumber)
        const reviewDecision = reviewByRound.get(roundNumber)
        const requestedDetails = (requestedDecision?.details ?? {}) as Record<string, any>
        const approvedDetails = (approvedDecision?.details ?? {}) as Record<string, any>
        const details = (reviewDecision?.details ?? {}) as Record<string, any>
        const evaluationSummary = (details.evaluation_summary ?? {}) as Record<string, any>

        return {
          roundNumber,
          requested: {
            candidateId: String(requestedDetails.candidate_id ?? ''),
            utilityScore: toNumber(requestedDetails.utility_score as NumericValue),
            summary: sanitizeText(requestedDecision?.summary ?? 'experiment requested', 180),
            metrics: candidateMetrics(
              candidateById.get(String(requestedDetails.candidate_id ?? '')),
            ),
          },
          approved: approvedDecision
            ? {
                candidateId: String(approvedDetails.candidate_id ?? ''),
                utilityScore: toNumber(approvedDetails.utility_score as NumericValue),
                summary: sanitizeText(approvedDecision.summary ?? 'experiment approved', 180),
                notes: sanitizeText(approvedDetails.notes ?? approvedDetails.human_feedback, 180),
                metrics: candidateMetrics(
                  candidateById.get(String(approvedDetails.candidate_id ?? '')),
                ),
              }
            : undefined,
          review: reviewDecision
            ? {
                experimentId: String(details.experiment_id ?? ''),
                summary: sanitizeText(reviewDecision.summary ?? 'round review requested', 180),
              }
            : undefined,
          notes: sanitizeText(evaluationSummary.robustness_recommendation, 180),
          hypothesisAssessments: Array.isArray(details.hypothesis_assessments)
            ? details.hypothesis_assessments
            : [],
          disagreementUpdates: Array.isArray(details.disagreement_updates)
            ? details.disagreement_updates
            : [],
        }
      }),
    stopHistory: snapshot.decisionLog.stop_history ?? [],
  }
}

function buildProcessMonitorViewModel(
  snapshot: LoaderSnapshot,
  currentRound: number,
): FrontendViewModels['processMonitor'] {
  const currentPhase = snapshot.process.current_phase
  const currentPhaseIndex = getPhaseIndex(currentPhase)
  const currentStepOrder = getPlanningStepOrder(snapshot.process.current_step)
  const latestDecisions = [...(snapshot.decisionLog.decisions ?? [])]
    .sort((a, b) => `${b.timestamp ?? ''}`.localeCompare(a.timestamp ?? ''))

  const planningSteps = [
    { id: 'step_1', label: '识别不确定性' },
    { id: 'step_2', label: '生成候选实验' },
    { id: 'step_3', label: '计算综合价值' },
    { id: 'step_4', label: '选择 E*' },
    { id: 'step_5', label: '生成协议' },
  ]

  const executionPhase = (snapshot.process as RawProcess & {
    phases?: Record<string, { steps?: Record<string, { name?: string; status?: string }> }>
  }).phases?.experiment_execution
  const executionSteps = Object.entries((executionPhase?.steps ?? {}) as Record<string, { name?: string; status?: string }>).map(
    ([id, step]) => {
      const status: 'completed' | 'running' | 'pending' =
        step?.status === 'completed' ? 'completed' : step?.status === 'in_progress' ? 'running' : 'pending'
      return {
        id,
        label: sanitizeText(step?.name ?? humanizeCode(id, id), 48),
        status,
      }
    },
  )

  const stages: FrontendViewModels['processMonitor']['stages'] = PHASE_ORDER.map((phase, index) => ({
    id: phase,
    label: PHASE_LABELS[phase],
    status:
      index < currentPhaseIndex
        ? 'completed'
        : index === currentPhaseIndex
          ? 'running'
          : 'pending',
    timestamp: latestDecisions.find((item) => item.phase === phase)?.timestamp,
    steps:
      phase === 'experiment_planning'
        ? planningSteps.map((step, stepIndex) => ({
            id: step.id,
            label: step.label,
            status:
              index < currentPhaseIndex
                ? 'completed'
                : index > currentPhaseIndex
                  ? 'pending'
                  : stepIndex + 1 < currentStepOrder
                    ? 'completed'
                    : stepIndex + 1 === currentStepOrder
                      ? 'running'
                      : 'pending',
          }))
        : phase === 'experiment_execution' && executionSteps.length > 0
          ? executionSteps
        : undefined,
  }))

  const pendingApproval = [...latestDecisions].find(
    (item) =>
      (item.round_id ?? currentRound) === currentRound &&
      item.decision_type === 'experiment_selection_requested',
  )

  return {
    currentRound,
    currentPhase: humanizePhase(currentPhase),
    currentStage: humanizeStage(snapshot.process.current_stage),
    currentStep: humanizeStep(snapshot.process.current_step),
    progressPercentage: snapshot.process.progress_percentage ?? 0,
    pendingApprovalCandidateId: String(pendingApproval?.details?.candidate_id ?? ''),
    stages,
    currentStepDetail: {
      title:
        snapshot.process.current_phase === 'experiment_planning'
          ? `Step ${currentStepOrder || 1}: ${planningSteps[Math.max(currentStepOrder - 1, 0)]?.label ?? '实验规划'}`
          : PHASE_LABELS[snapshot.process.current_phase ?? ''] ?? '当前步骤',
      status: humanizeStage(snapshot.process.current_stage),
      candidateCount: getSelectableCandidates(snapshot).length,
      recommendedExperimentId:
        getSelectableCandidates(snapshot).sort(
          (a, b) => toNumber(b.utility_score) - toNumber(a.utility_score),
        )[0]?.experiment_id,
    },
    recentLogs: latestDecisions.slice(0, 8).map((item, index) => ({
      id: item.decision_id ?? `log-${index + 1}`,
      timestamp: item.timestamp,
      summary: sanitizeText(item.summary ?? item.decision_type ?? '', 180),
    })),
  }
}

function buildRoundReportViewModel(
  snapshot: LoaderSnapshot,
  currentRound: number,
): FrontendViewModels['roundReport'] {
  const reportRound = Math.max(1, currentRound - (snapshot.process.current_phase === 'next_round' ? 0 : 1))
  const latestEntry =
    [...(snapshot.experimentMemory.entries ?? [])]
      .filter((item) => (item.round_id ?? 0) <= reportRound)
      .sort((a, b) => (b.round_id ?? 0) - (a.round_id ?? 0))[0] ?? null
  const highlightedHypotheses = buildHypothesisPreviews(reportRound, currentRound, snapshot.hypothesisTree)
  const unresolvedQuestions = buildUncertaintyPreviews(
    reportRound,
    currentRound,
    snapshot.uncertainties,
    snapshot.plannerInput,
    12,
  ).map((item) => item.title)

  return {
    roundNumber: reportRound,
    recommendedAction:
      snapshot.process.user_requests?.stop_requested
        ? 'stop'
        : unresolvedQuestions.length > 0
          ? 'next_round'
          : 'adjust',
    summary: {
      baselinePearsonR: latestEntry?.metrics_snapshot?.baseline_pearson_r,
      treatmentPearsonR: latestEntry?.metrics_snapshot?.treatment_pearson_r,
      deltaPearsonR: latestEntry?.metrics_snapshot?.delta?.pearson_r,
      baselineRmse: latestEntry?.metrics_snapshot?.baseline_rmse,
      treatmentRmse: latestEntry?.metrics_snapshot?.treatment_rmse,
      deltaRmse: latestEntry?.metrics_snapshot?.delta?.rmse,
    },
    scientificConclusions: uniqueStrings(
      [
        ...(latestEntry?.key_findings ?? []),
        ...(snapshot.plannerInput.recent_hypothesis_assessments ?? []).map(
          (item) =>
            `${item.hypothesis_id} ${Number(item.support_after ?? 0) >= Number(item.support_before ?? 0) ? '获得加强' : '被削弱'} (${Number(
              item.support_after ?? 0,
            ).toFixed(3)})`,
        ),
      ],
      160,
    ).slice(0, 5),
    highlightedHypotheses,
    unresolvedQuestions,
    decisionOptions: ['进入下一轮', '调整方向', '停止实验'],
  }
}

function buildApprovalOverlayViewModel(
  snapshot: LoaderSnapshot,
  currentRound: number,
): FrontendViewModels['approvalOverlay'] {
  const sortedCandidates = getSelectableCandidates(snapshot).sort(
    (a, b) => toNumber(b.utility_score) - toNumber(a.utility_score),
  )
  const topCandidate = sortedCandidates[0]

  return {
    roundNumber: currentRound,
    isPending: snapshot.process.current_stage === 'awaiting_human_approval',
    recommendation: {
      candidateId: topCandidate?.experiment_id,
      reason: topCandidate
        ? `${topCandidate.experiment_id} 信息增益 ${toNumber(topCandidate.estimated_information_gain).toFixed(3)}，综合价值 ${toNumber(topCandidate.utility_score).toFixed(3)}。`
        : '当前没有候选实验。',
      evidence: [
        topCandidate?.scientific_question ?? topCandidate?.purpose ?? '当前没有可用的实验问题摘要。',
      ],
    },
    candidates: sortedCandidates.slice(0, 5).map((item, index) => ({
      experimentId: item.experiment_id ?? `candidate-${index + 1}`,
      scientificQuestion: sanitizeText(item.scientific_question ?? item.purpose ?? '暂无实验说明', 180),
      informationGain: toNumber(item.estimated_information_gain),
      performanceGain: toNumber(item.estimated_performance_gain),
      risk: toNumber(item.estimated_risk),
      cost: toNumber(item.estimated_cost),
      utility: toNumber(item.utility_score),
      recommended: index === 0,
      relatedUncertainties: Array.isArray((item as Record<string, unknown>).related_uncertainties)
        ? ((item as Record<string, unknown>).related_uncertainties as string[])
        : [],
      testedHypotheses: Array.isArray(item.tested_hypotheses) ? item.tested_hypotheses : [],
      controlVariables: getExperimentValidationSnapshot(item).controlVariables,
      treatmentVariables: getExperimentValidationSnapshot(item).treatmentVariables,
      experimentMode: getExperimentValidationSnapshot(item).experimentMode,
      hasFeatureDifference: getExperimentValidationSnapshot(item).hasFeatureDifference,
    })),
    competitionChecklist: [
      {
        label: '闭环留痕',
        status: 'ready',
        summary: '候选实验、审批与轮次结果均已写入运行态状态文件。',
      },
      {
        label: '证据承接',
        status: 'ready',
        summary: '候选实验继续承接上一轮不确定性与 tested hypotheses。',
      },
    ],
    iterationSignals: sortedCandidates.slice(0, 2).map((item) =>
      sanitizeText(item.scientific_question ?? item.purpose ?? '下一轮将继续围绕当前关键不确定性推进。', 120),
    ),
  }
}

function buildDecisionLogViewerViewModel(
  snapshot: LoaderSnapshot,
): FrontendViewModels['decisionLogViewer'] {
  const decisionRecords = (snapshot.decisionLog.decisions ?? []).map((item, index) => ({
    id: item.decision_id ?? `decision-${index + 1}`,
    timestamp: item.timestamp,
    roundNumber: item.round_id,
    type: item.decision_type ?? 'decision',
    actor: item.made_by ?? 'system',
    summary: sanitizeText(item.summary ?? item.decision_type ?? '', 220),
    details: Object.entries((item.details ?? {}) as Record<string, unknown>)
      .slice(0, 4)
      .map(([key, value]) => `${key}: ${sanitizeText(value, 80)}`),
  }))
  const feedbackRecords = (snapshot.decisionLog.human_feedback ?? []).map((item, index) => {
    const feedback = item as Record<string, unknown>
    return {
      id: item.feedback_id ?? `feedback-${index + 1}`,
      timestamp: item.timestamp,
      roundNumber:
        typeof feedback.round_id === 'number'
          ? (feedback.round_id as number)
          : item.round_number,
      type: 'human_feedback',
      actor: 'human_pi',
      summary: sanitizeText(item.content ?? '', 220),
      details: [
        typeof feedback.target === 'string' ? `target: ${sanitizeText(feedback.target, 80)}` : '',
        typeof feedback.action === 'string' ? `action: ${sanitizeText(feedback.action, 80)}` : '',
      ].filter(Boolean),
    }
  })

  const records = [...decisionRecords, ...feedbackRecords].sort((a, b) =>
    `${b.timestamp ?? ''}`.localeCompare(`${a.timestamp ?? ''}`),
  )

  return {
    records,
    availableTypes: [...new Set(records.map((item) => item.type))].sort(),
    availableActors: [...new Set(records.map((item) => item.actor))].sort(),
  }
}

function buildDataManagerViewModel(
  snapshot: LoaderSnapshot,
): FrontendViewModels['dataManager'] {
  const dataSources = snapshot.task.payload?.data_sources ?? {}
  const variables = snapshot.task.payload?.research_question?.variables ?? {}
  const resourceBudget = (snapshot.task.payload?.constraints?.resource_budget ?? {}) as Record<string, unknown>
  const sourceEntries = Object.entries(dataSources).map(([id, value]) => {
    const source = (value ?? {}) as Record<string, unknown>
    return {
      id,
      path: typeof source.path === 'string' ? source.path : undefined,
      timeColumn: typeof source.time_column === 'string' ? source.time_column : undefined,
      targetColumn: typeof source.target_column === 'string' ? source.target_column : undefined,
      role: id === 'omni' ? '主预测数据源' : '辅助科学观测源',
    }
  })

  const variableDictionary = [
    ...(variables.x
      ? [
          {
            field: String(variables.x),
            meaning: '核心科学解释变量',
            source: sourceEntries.find((item) => item.id === 'lhaaso')?.id ?? '主观测源',
          },
        ]
      : []),
    ...(variables.y
      ? [
          {
            field: String(variables.y),
            meaning: '预测目标变量',
            source: sourceEntries.find((item) => item.id === 'omni')?.id ?? '主目标数据源',
          },
        ]
      : []),
    ...((variables.m_candidates ?? []) as string[]).map((item) => ({
      field: item,
      meaning: '候选中介 / 控制变量',
      source: sourceEntries.find((entry) => entry.id === 'omni')?.id ?? '辅助数据源',
    })),
  ]

  return {
    sources: sourceEntries,
    variableDictionary,
    resourceBudget: Object.entries(resourceBudget).map(([label, value]) => ({
      label: formatBudgetLabel(label),
      value: String(value),
    })),
    qualityChecks: [
      {
        id: 'alignment',
        label: '时间对齐',
        status: sourceEntries.every((item) => item.timeColumn) ? 'pass' : 'warning',
        note: sourceEntries.every((item) => item.timeColumn) ? '已提供时间列，可执行对齐。' : '存在缺失时间列的数据源。',
      },
      {
        id: 'target',
        label: '目标字段映射',
        status: variables.y
          ? sourceEntries.some((item) => item.targetColumn === String(variables.y)) ? 'pass' : 'warning'
          : 'warning',
        note: variables.y ? `目标变量 ${String(variables.y)} 已映射到当前数据源。` : '尚未识别目标变量字段。',
      },
      {
        id: 'constraints',
        label: '资源预算',
        status: 'pass',
        note: `token=${String(resourceBudget.token_budget ?? '--')} / time=${String(resourceBudget.max_time_seconds_per_round ?? '--')}s`,
      },
    ],
  }
}

function buildKnowledgeBaseManagerViewModel(
  snapshot: LoaderSnapshot,
): FrontendViewModels['knowledgeBaseManager'] {
  const traces = snapshot.plannerInput.recent_reasoning_traces ?? []
  const projectEntries = traces.filter((item) => item.stage?.includes('rag_project'))
  const literatureEntries = traces.filter((item) => item.stage?.includes('rag_literature'))
  const otherEntries = traces.filter(
    (item) => !item.stage?.includes('rag_project') && !item.stage?.includes('rag_literature'),
  )

  const researchQuestion = (snapshot.task.payload?.research_question ?? {}) as Record<string, unknown>
  return {
    collections: [
      {
        id: 'project',
        label: '项目信息库',
        count: projectEntries.length,
        status: projectEntries.length > 0 ? 'ready' : 'partial',
        summary: '承载项目状态、实验上下文和历史决策。',
      },
      {
        id: 'literature',
        label: '文献知识库',
        count: literatureEntries.length,
        status: literatureEntries.length > 0 ? 'ready' : 'partial',
        summary: '承载外部科学文献与背景知识摘要。',
      },
      {
        id: 'reasoning',
        label: '推理痕迹库',
        count: otherEntries.length,
        status: otherEntries.length > 0 ? 'ready' : 'partial',
        summary: '记录假设提出者、解释者等智能体的关键推理片段。',
      },
    ],
    ragEntries: traces.slice(0, 12).map((item, index) => ({
      id: item.trace_id ?? `trace-${index + 1}`,
      stage: item.stage ?? 'unknown',
      summary: sanitizeText(item.summary ?? '', 180),
      hypotheses: Array.isArray(item.related_hypotheses) ? item.related_hypotheses.slice(0, 3) : [],
      uncertainties: Array.isArray(item.related_uncertainties) ? item.related_uncertainties.slice(0, 3) : [],
    })),
    uploads: (snapshot.uploadManifest?.records ?? []).map((item, index) => ({
      id: `upload-${index + 1}`,
      fileName: item.file_name ?? '未命名文件',
      fileType: item.file_type ?? 'unknown',
      uploadedAt: item.uploaded_at,
      extractionStatus:
        item.extraction_status === 'ready'
          ? '已完成文本抽取'
          : item.extraction_status === 'placeholder_only'
            ? '仅记录占位文本'
            : '待处理',
      syncStatus:
        item.knowledge_sync_status === 'local_session_only'
          ? '仅写入当前本地会话'
          : item.knowledge_sync_status ?? '未知',
      storagePath: item.storage_path ?? '未记录',
      note: item.knowledge_sync_note ?? '未记录同步说明。',
    })),
    modelUsage: [
      ...(snapshot.modelUsage?.session_model
        ? [
            {
              scope: formatModelScope('session'),
              model: snapshot.modelUsage.session_model,
              purpose: '当前中央控制页默认请求模型',
            },
          ]
        : []),
      ...((snapshot.modelUsage?.routes ?? []).map((item) => ({
        scope: formatModelScope(item.route ?? 'route'),
        model: item.model ?? '--',
        purpose: item.purpose ?? '未记录用途',
      })) ?? []),
      ...((snapshot.modelUsage?.roles ?? []).map((item) => ({
        scope: formatModelScope(item.role ?? 'role'),
        model: item.model ?? '--',
        purpose: '闭环内部角色推理调用',
      })) ?? []),
    ],
    tags: uniqueStrings([
      ...((Array.isArray(researchQuestion.keywords) ? researchQuestion.keywords : []) as string[]),
      ...((snapshot.plannerInput.unresolved_uncertainties ?? []).map((item) => item.uncertainty_id) ?? []),
      ...((snapshot.plannerInput.active_hypotheses ?? []).map((item) => item.hypothesis_id) ?? []),
    ]),
  }
}

async function loadSnapshotFromSource(source: StateSource): Promise<LoaderSnapshot> {
  const [
    task,
    process,
    hypothesisTree,
    uncertainties,
    experimentMemory,
    decisionLog,
    candidateExperiments,
    plannerInput,
    plannerOutput,
    uploadManifest,
    modelUsage,
    sessionStatus,
  ] = await Promise.all([
    readJson<RawTask>(joinSourcePath(source.baseUrl, SOURCE_FILES.task)),
    readJson<RawProcess>(joinSourcePath(source.baseUrl, SOURCE_FILES.process)),
    readJson<RawHypothesisTree>(joinSourcePath(source.baseUrl, SOURCE_FILES.hypothesisTree)),
    readJson<RawUncertainties>(joinSourcePath(source.baseUrl, SOURCE_FILES.uncertainties)),
    readJson<RawExperimentMemory>(joinSourcePath(source.baseUrl, SOURCE_FILES.experimentMemory)),
    readJson<RawDecisionLog>(joinSourcePath(source.baseUrl, SOURCE_FILES.decisionLog)),
    readJsonOptional<RawCandidateExperiments>(joinSourcePath(source.baseUrl, SOURCE_FILES.candidateExperiments)),
    readJsonOptional<RawPlannerInput>(joinSourcePath(source.baseUrl, SOURCE_FILES.plannerInput)),
    readJsonOptional(joinSourcePath(source.baseUrl, SOURCE_FILES.plannerOutput)),
    readJsonOptional<RawUploadManifest>(joinSourcePath(source.baseUrl, SOURCE_FILES.uploadManifest)),
    readJsonOptional<RawModelUsage>(joinSourcePath(source.baseUrl, SOURCE_FILES.modelUsage)),
    readSessionStatus(),
  ])

  return {
    task,
    process,
    decisionLog,
    hypothesisTree,
    uncertainties,
    experimentMemory,
    candidateExperiments: candidateExperiments ?? ({} as RawCandidateExperiments),
    plannerInput: plannerInput ?? ({} as RawPlannerInput),
    plannerOutput,
    sessionStatus,
    uploadManifest: uploadManifest ?? { records: [] },
    modelUsage: modelUsage ?? { routes: [], roles: [] },
  }
}

export async function loadFrontendStateSnapshot(): Promise<{
  snapshot: LoaderSnapshot
  sourceMode: 'api' | 'empty'
}> {
  const sources = getStateSources()
  if (sources.length === 0) {
    throw new Error('未配置真实运行服务地址，前端不会加载本地演示数据。')
  }

  try {
    const snapshot = await loadSnapshotFromSource(sources[0])
    if (isSnapshotStaleAfterReset(snapshot, snapshot.sessionStatus ?? null)) {
      return {
        snapshot: createEmptySnapshot({
          status: 'idle',
          stage: 'waiting_input',
          currentRound: 0,
        }),
        sourceMode: 'empty',
      }
    }
    return {
      snapshot,
      sourceMode: 'api',
    }
  } catch (error) {
    const session = await readSessionStatus()
    const emptyAllowed =
      session &&
      (session.stage === 'waiting_input' ||
        session.stage === 'workspace_preparing' ||
        session.status === 'idle' ||
        session.status === 'starting')

    if (emptyAllowed) {
      return {
        snapshot: createEmptySnapshot(session),
        sourceMode: 'empty',
      }
    }

    throw new Error(
      error instanceof Error
        ? error.message
        : '真实运行状态读取失败，请确认本地服务已启动且当前会话已初始化。',
    )
  }
}

export function buildViewModels(snapshot: LoaderSnapshot): FrontendViewModels {
  const roundNumbers = collectRoundNumbers(snapshot)
  const currentRound = inferCurrentRound(roundNumbers, snapshot)
  const rounds = roundNumbers.map((roundNumber) => buildRoundData(roundNumber, currentRound, snapshot))
  const currentRoundData = rounds.find((item) => item.roundNumber === currentRound) ?? rounds[rounds.length - 1]
  const currentNodeId =
    currentRoundData?.nodes.find((item) => item.status === 'active' || item.status === 'approval')?.id ??
    currentRoundData?.nodes[0]?.id ??
    null

  return {
    rounds,
    currentRoundNumber: currentRound,
    currentRoundId: currentRoundData?.id ?? `round-${currentRound}`,
    currentNodeId,
    progressPercentage: snapshot.process.progress_percentage ?? 0,
    processStage: snapshot.process.current_stage ?? 'unknown',
    mission: buildMissionViewModel(snapshot),
    knowledgeMemory: buildKnowledgeMemoryViewModel(snapshot),
    experimentEvaluation: buildExperimentEvaluationViewModel(snapshot, currentRound),
    governance: buildGovernanceViewModel(snapshot, currentRound),
    processMonitor: buildProcessMonitorViewModel(snapshot, currentRound),
    roundReport: buildRoundReportViewModel(snapshot, currentRound),
    approvalOverlay: buildApprovalOverlayViewModel(snapshot, currentRound),
    decisionLogViewer: buildDecisionLogViewerViewModel(snapshot),
    dataManager: buildDataManagerViewModel(snapshot),
    knowledgeBaseManager: buildKnowledgeBaseManagerViewModel(snapshot),
  }
}

export async function loadTimelineBundle(): Promise<TimelineDataBundle> {
  const { snapshot, sourceMode } = await loadFrontendStateSnapshot()
  return {
    snapshot,
    viewModels: buildViewModels(snapshot),
    sourceMode,
    refreshedAt: new Date().toISOString(),
  }
}
