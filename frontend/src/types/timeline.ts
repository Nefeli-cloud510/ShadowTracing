export type TimelineNodeStatus =
  | 'completed'
  | 'active'
  | 'pending'
  | 'approval'
  | 'paused'

export type CorePageId =
  | 'workflow'
  | 'dialogue'
  | 'data-dictionary'
  | 'hypotheses'
  | 'uncertainties'
  | 'approval'
  | 'execution'
  | 'report'

export interface TimelineNodeData {
  id: string
  shortLabel: string
  title: string
  summary: string
  status: TimelineNodeStatus
  detailItems?: string[]
  relatedPage?: Exclude<CorePageId, 'home'>
}

export interface HypothesisPreviewNode {
  id: string
  label: string
  status: 'active' | 'newly_split' | 'observing' | 'weakened'
  supportScore: number
  level?: number
}

export interface UncertaintyPreview {
  id: string
  title: string
  priority: 'P1' | 'P2' | 'P3'
  resolutionStatus: 'open' | 'tracking' | 'resolved'
  relatedHypotheses?: string[]
}

export interface ExperimentPreview {
  id: string
  targetHypothesis: string
  utility: number
  informationGain: number
  performanceGain: number
  status: 'recommended' | 'candidate' | 'approved' | 'completed'
  scientificQuestion?: string
}

export interface EvaluationPreview {
  experimentId?: string
  baselinePearsonR?: number
  treatmentPearsonR?: number
  deltaPearsonR: number
  deltaRmse?: number
  pgActual: number
  verdict: 'supports' | 'weakens' | 'mixed'
  stable?: boolean
}

export interface RoundData {
  id: string
  roundNumber: number
  title: string
  subtitle: string
  stateLabel: string
  questionSummary: string
  isCurrent: boolean
  isCollapsed: boolean
  nodes: TimelineNodeData[]
  hypotheses: HypothesisPreviewNode[]
  uncertainties: UncertaintyPreview[]
  experiments: ExperimentPreview[]
  evaluation?: EvaluationPreview
}

export interface MissionViewModel {
  scientificQuestion: string
  target: string
  questionType: string
  variables: {
    x?: string
    y?: string
    mCandidates: string[]
  }
  constraints: string[]
  metrics: string[]
  dataSources: Array<{
    id: string
    path?: string
    timeColumn?: string
    targetColumn?: string
  }>
  piGuidance: Array<{
    id: string
    timestamp?: string
    roundNumber?: number
    content: string
    source: string
  }>
  dialogueMessages: Array<{
    id: string
    role: 'system' | 'agent' | 'user'
    speaker: string
    content: string
    timestamp?: string
  }>
  expertStates: Array<{
    id: string
    label: string
    status: 'active' | 'completed' | 'running' | 'waiting'
    summary: string
  }>
}

export interface KnowledgeMemoryViewModel {
  rootQuestion: string
  treeSummary: {
    totalNodes: number
    activeCount: number
    prunedCount: number
    pendingCount: number
  }
  highlightedHypotheses: HypothesisPreviewNode[]
  allHypotheses: any[]
  uncertaintyQueue: Array<{
    id: string
    question: string
    priorityScore: number
    status: string
    estimatedResolutionRound?: number
  }>
  uncertaintyRecords: any[]
  experimentEntries: any[]
  ragSummaries: {
    project: string[]
    literature: string[]
    external: string[]
  }
}

export interface ExperimentEvaluationViewModel {
  recommendedExperimentId?: string
  candidateExperiments: any[]
  experimentEntries: any[]
  latestEvaluation?: EvaluationPreview
  metricComparison?: {
    baselineRmse?: number
    treatmentRmse?: number
    baselinePearsonR?: number
    treatmentPearsonR?: number
    deltaPearsonR?: number
    deltaRmse?: number
  }
  visualizationPaths: string[]
  visualizationItems: Array<{
    path: string
    label: string
    previewUrl: string
    variant: 'baseline' | 'treatment' | 'artifact'
  }>
}

export interface GovernanceDecisionsViewModel {
  processSummary: {
    currentPhase?: string
    currentStage?: string
    currentStep?: string
    autoContinue: boolean
    stopRequested: boolean
  }
  pendingApproval?: {
    candidateId?: string
    utilityScore?: number
    summary: string
  }
  approvals: any[]
  roundReviews: any[]
  auditTrail: any[]
  approvalComparisons: Array<{
    roundNumber: number
    requested: {
      candidateId: string
      utilityScore: number
      summary: string
      metrics: {
        informationGain: number
        performanceGain: number
        risk: number
        cost: number
        utility: number
      }
    }
    approved?: {
      candidateId: string
      utilityScore: number
      summary: string
      notes?: string
      metrics: {
        informationGain: number
        performanceGain: number
        risk: number
        cost: number
        utility: number
      }
    }
    review?: {
      experimentId?: string
      summary: string
    }
    notes?: string
    hypothesisAssessments: any[]
    disagreementUpdates: any[]
  }>
  stopHistory: any[]
}

export interface ProcessMonitorViewModel {
  currentRound: number
  currentPhase?: string
  currentStage?: string
  currentStep?: string
  progressPercentage: number
  pendingApprovalCandidateId?: string
  stages: Array<{
    id: string
    label: string
    status: 'completed' | 'running' | 'pending'
    timestamp?: string
    steps?: Array<{
      id: string
      label: string
      status: 'completed' | 'running' | 'pending'
    }>
  }>
  currentStepDetail: {
    title: string
    status: string
    candidateCount: number
    recommendedExperimentId?: string
  }
  recentLogs: Array<{
    id: string
    timestamp?: string
    summary: string
  }>
}

export interface RoundReportViewModel {
  roundNumber: number
  recommendedAction: 'next_round' | 'adjust' | 'stop'
  summary: {
    baselinePearsonR?: number
    treatmentPearsonR?: number
    deltaPearsonR?: number
    baselineRmse?: number
    treatmentRmse?: number
    deltaRmse?: number
  }
  scientificConclusions: string[]
  highlightedHypotheses: HypothesisPreviewNode[]
  unresolvedQuestions: string[]
  decisionOptions: string[]
}

export interface ApprovalOverlayViewModel {
  roundNumber: number
  isPending: boolean
  recommendation: {
    candidateId?: string
    reason: string
    evidence: string[]
  }
  candidates: Array<{
    experimentId: string
    scientificQuestion: string
    informationGain: number
    performanceGain: number
    risk: number
    cost: number
    utility: number
    recommended: boolean
    relatedUncertainties: string[]
    testedHypotheses: string[]
  }>
  competitionChecklist: Array<{
    label: string
    status: 'ready' | 'partial'
    summary: string
  }>
  iterationSignals: string[]
}

export interface DecisionLogViewerViewModel {
  records: Array<{
    id: string
    timestamp?: string
    roundNumber?: number
    type: string
    actor: string
    summary: string
    details: string[]
  }>
  availableTypes: string[]
  availableActors: string[]
}

export interface DataManagerViewModel {
  sources: Array<{
    id: string
    path?: string
    timeColumn?: string
    targetColumn?: string
    role: string
  }>
  variableDictionary: Array<{
    field: string
    meaning: string
    source: string
  }>
  resourceBudget: Array<{
    label: string
    value: string
  }>
  qualityChecks: Array<{
    id: string
    label: string
    status: 'pass' | 'warning'
    note: string
  }>
}

export interface KnowledgeBaseManagerViewModel {
  collections: Array<{
    id: string
    label: string
    count: number
    status: 'ready' | 'partial'
    summary: string
  }>
  ragEntries: Array<{
    id: string
    stage: string
    summary: string
    hypotheses: string[]
    uncertainties: string[]
  }>
  uploads: Array<{
    id: string
    fileName: string
    fileType: string
    uploadedAt?: string
    extractionStatus: string
    syncStatus: string
    storagePath: string
    note: string
  }>
  modelUsage: Array<{
    scope: string
    model: string
    purpose: string
  }>
  tags: string[]
}

export interface FrontendStateSnapshot {
  task: any
  process: any
  decisionLog: any
  hypothesisTree: any
  uncertainties: any
  experimentMemory: any
  candidateExperiments: any
  plannerInput: any
  plannerOutput: any | null
  sessionStatus?: any
  uploadManifest?: any
  modelUsage?: any
}

export interface FrontendViewModels {
  rounds: RoundData[]
  currentRoundNumber: number
  currentRoundId: string
  currentNodeId: string | null
  progressPercentage: number
  processStage: string
  mission: MissionViewModel
  knowledgeMemory: KnowledgeMemoryViewModel
  experimentEvaluation: ExperimentEvaluationViewModel
  governance: GovernanceDecisionsViewModel
  processMonitor: ProcessMonitorViewModel
  roundReport: RoundReportViewModel
  approvalOverlay: ApprovalOverlayViewModel
  decisionLogViewer: DecisionLogViewerViewModel
  dataManager: DataManagerViewModel
  knowledgeBaseManager: KnowledgeBaseManagerViewModel
}

export interface TimelineDataBundle {
  snapshot: FrontendStateSnapshot
  viewModels: FrontendViewModels
  sourceMode: 'api' | 'empty'
  refreshedAt: string
}
