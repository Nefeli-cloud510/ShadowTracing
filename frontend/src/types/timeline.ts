export type TimelineNodeStatus =
  | 'completed'
  | 'active'
  | 'pending'
  | 'approval'
  | 'paused'

export interface TimelineNodeData {
  id: string
  shortLabel: string
  title: string
  summary: string
  status: TimelineNodeStatus
  detailItems?: string[]
}

export interface HypothesisPreviewNode {
  id: string
  label: string
  status: 'active' | 'newly_split' | 'observing' | 'weakened'
  supportScore: number
}

export interface UncertaintyPreview {
  id: string
  title: string
  priority: 'P1' | 'P2' | 'P3'
  resolutionStatus: 'open' | 'tracking' | 'resolved'
}

export interface ExperimentPreview {
  id: string
  targetHypothesis: string
  utility: number
  informationGain: number
  performanceGain: number
  status: 'recommended' | 'candidate' | 'approved'
}

export interface EvaluationPreview {
  deltaPearsonR: number
  pgActual: number
  verdict: 'supports' | 'weakens' | 'mixed'
}

export interface RoundData {
  id: string
  title: string
  subtitle: string
  stateLabel: string
  questionSummary: string
  nodes: TimelineNodeData[]
  hypotheses: HypothesisPreviewNode[]
  uncertainties: UncertaintyPreview[]
  experiments: ExperimentPreview[]
  evaluation?: EvaluationPreview
  rawHypothesisTree?: any
  rawDecisionLog?: any
  rawCandidateExperiments?: any
}

export interface TimelineDataBundle {
  round: RoundData
  currentRoundNumber: number
  progressPercentage: number
  processStage: string
}
