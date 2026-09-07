const LOCAL_API_ORIGIN =
  typeof window !== 'undefined' && /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname)
    ? 'http://127.0.0.1:8765'
    : ''

const API_ROOT =
  typeof import.meta !== 'undefined'
    ? import.meta.env.VITE_WORKFLOW_API_BASE?.trim() ?? (LOCAL_API_ORIGIN ? `${LOCAL_API_ORIGIN}/api` : '/api')
    : ''

export interface StartWorkflowPayload {
  question: string
  knowledgeFiles: File[]
  dataFiles?: File[]
  model?: string
  rounds?: number
  xVariable?: string
  yVariable?: string
  mCandidates?: string[]
  questionType?: string
  dataDictionaryConfig?: {
    time_column?: string
    fields: Array<{
      field_name: string
      file_name?: string
      category?: string
      physical_meaning?: string
      display_name?: string
    }>
  }
}

export interface LiveWorkflowResponse {
  status: string
  stage?: string
  planning_status?: string
  message?: string
  question?: string
  currentRound?: number
  runRoot?: string
}

export interface UncertaintyRecoveryResult extends LiveWorkflowResponse {
  mode?: 'extend' | 'retry' | 'manual'
  currentRound?: number
  targetCount?: number
  activeCount?: number
  addedCount?: number
  added?: string[]
  skippedDuplicates?: number
  sourceDetailCounts?: Record<string, number>
}

export interface ManualUncertaintyItem {
  question: string
  description?: string
  priority?: 'low' | 'medium' | 'high'
  relatedHypotheses?: string[]
  features?: string[]
}

export function reportExportUrl(scope: 'round' | 'all', roundNumber?: number): string {
  if (!API_ROOT) {
    return ''
  }
  const query = scope === 'all' ? 'scope=all' : `scope=round&round=${roundNumber ?? 1}`
  return `${API_ROOT}/report/export?${query}`
}

export interface QuestionAnalysis {
  x_variable?: string
  y_variable?: string
  m_candidates: string[]
  question_type?: string
  needs_confirmation: boolean
  clarification_question?: string
  rationale?: string
}

export interface DataInspectionColumn {
  field_name: string
  data_type: string
  is_numeric: boolean
  missing_rate: number
  suggested_category: string
  physical_meaning: string
  display_name?: string
}

export interface DataInspectionTable {
  file_name: string
  row_count: number
  columns: DataInspectionColumn[]
}

export interface DataInspectionResult {
  tables: DataInspectionTable[]
  suggested: {
    time_column?: string
    target_variable?: string
    core_explanatory?: string
    candidate_mediators: string[]
  }
}

async function parseJsonResponse(response: Response): Promise<LiveWorkflowResponse> {
  const text = await response.text()
  if (!text.trim()) {
    return { status: response.ok ? 'ok' : 'error' }
  }

  try {
    return JSON.parse(text) as LiveWorkflowResponse
  } catch {
    return {
      status: response.ok ? 'ok' : 'error',
      message: text,
    }
  }
}

export async function startWorkflow(payload: StartWorkflowPayload): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法启动真实闭环。')
  }

  const formData = new FormData()
  formData.append('question', payload.question)
  formData.append('model', payload.model ?? 'qwen3.8-flash')
  formData.append('rounds', String(payload.rounds ?? 2))
  if (payload.xVariable?.trim()) {
    formData.append('x_variable', payload.xVariable.trim())
  }
  if (payload.yVariable?.trim()) {
    formData.append('y_variable', payload.yVariable.trim())
  }
  if (payload.questionType?.trim()) {
    formData.append('question_type', payload.questionType.trim())
  }
  if (payload.mCandidates?.length) {
    formData.append('m_candidates', JSON.stringify(payload.mCandidates))
  }
  if (payload.dataDictionaryConfig) {
    formData.append('data_dictionary_config', JSON.stringify(payload.dataDictionaryConfig))
  }

  for (const file of payload.knowledgeFiles) {
    formData.append('knowledge_files', file, file.name)
  }
  for (const file of payload.dataFiles ?? []) {
    formData.append('data_files', file, file.name)
  }

  const response = await fetch(`${API_ROOT}/workflow/start`, {
    method: 'POST',
    body: formData,
  })
  const result = await parseJsonResponse(response)

  if (!response.ok) {
    throw new Error(result.message ?? '真实闭环启动失败。')
  }

  return result
}

export async function resetWorkflow(
  options: { preserveUploadedFiles?: boolean } = {},
): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    return { status: 'idle' }
  }

  const response = await fetch(`${API_ROOT}/session/reset`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      preserve_uploaded_files: options.preserveUploadedFiles === true,
    }),
  })
  const result = await parseJsonResponse(response)

  if (!response.ok) {
    throw new Error(result.message ?? '重置运行状态失败。')
  }

  return result
}

export async function analyzeQuestion(question: string, model = 'qwen3.8-flash'): Promise<QuestionAnalysis> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法解析科学问题。')
  }

  const response = await fetch(`${API_ROOT}/session/analyze-question`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ question, model }),
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '科学问题解析失败。')
  }
  return (result as LiveWorkflowResponse & { analysis?: QuestionAnalysis }).analysis ?? {
    m_candidates: [],
    needs_confirmation: true,
  }
}

export async function inspectDataFiles(dataFiles: File[]): Promise<DataInspectionResult> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法检查实验数据。')
  }
  if (dataFiles.length === 0) {
    throw new Error('请先上传实验数据文件。')
  }

  const formData = new FormData()
  for (const file of dataFiles) {
    formData.append('data_files', file, file.name)
  }

  const response = await fetch(`${API_ROOT}/session/inspect-data`, {
    method: 'POST',
    body: formData,
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '实验数据检查失败。')
  }
  return (result as LiveWorkflowResponse & { inspection?: DataInspectionResult }).inspection ?? {
    tables: [],
    suggested: { candidate_mediators: [] },
  }
}

export async function stageDataFiles(dataFiles: File[]): Promise<DataInspectionResult> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法上传实验数据。')
  }
  if (dataFiles.length === 0) {
    throw new Error('请先上传实验数据文件。')
  }

  const formData = new FormData()
  for (const file of dataFiles) {
    formData.append('data_files', file, file.name)
  }

  const response = await fetch(`${API_ROOT}/session/stage-data`, {
    method: 'POST',
    body: formData,
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '实验数据上传后端失败。')
  }
  return (result as LiveWorkflowResponse & { inspection?: DataInspectionResult }).inspection ?? {
    tables: [],
    suggested: { candidate_mediators: [] },
  }
}

export async function inspectStagedDataFiles(): Promise<DataInspectionResult | null> {
  if (!API_ROOT) {
    return null
  }

  const response = await fetch(`${API_ROOT}/session/staged-inspect`, {
    method: 'GET',
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    return null
  }
  return (result as LiveWorkflowResponse & { inspection?: DataInspectionResult }).inspection ?? null
}

export async function submitApprovalAction(payload: {
  action: 'approve' | 'modify' | 'reject' | 'pause'
  candidateId?: string
  humanNotes?: string
  modelParameters?: Record<string, unknown>
}): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法提交审批动作。')
  }

  const response = await fetch(`${API_ROOT}/workflow/approval`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '审批动作提交失败。')
  }
  return result
}

export async function submitRoundDecision(payload: {
  decision: 'continue' | 'adjust' | 'stop'
  humanFeedback?: string
}): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法提交整轮反馈。')
  }

  const response = await fetch(`${API_ROOT}/workflow/round-decision`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '整轮反馈提交失败。')
  }
  return result
}

export async function confirmHypothesisTree(payload?: {
  humanNotes?: string
  nodes?: Array<Record<string, unknown>>
}): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法确认假设树。')
  }

  const response = await fetch(`${API_ROOT}/workflow/confirm-hypothesis`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload ?? {}),
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '假设树确认失败。')
  }
  return result
}

export async function runScientificQuestioning(): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法启动科学质询。')
  }

  const response = await fetch(`${API_ROOT}/workflow/scientific-questioning`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({}),
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '科学质询启动失败。')
  }
  return result
}

export async function rerunScientificQuestioning(): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法重新生成科学质询。')
  }

  const response = await fetch(`${API_ROOT}/workflow/scientific-questioning/rerun`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({}),
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '科学质询重新生成失败。')
  }
  return result
}

export async function undoScientificQuestioning(): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法撤销科学质询。')
  }

  const response = await fetch(`${API_ROOT}/workflow/scientific-questioning/undo`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({}),
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '科学质询撤销失败。')
  }
  return result
}

export async function startUncertaintyIdentification(): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法进入不确定性识别。')
  }

  const response = await fetch(`${API_ROOT}/workflow/start-uncertainty-identification`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({}),
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '不确定性识别启动失败。')
  }
  return result
}

export async function regenerateCandidatePlan(): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法重新生成候选实验。')
  }

  const response = await fetch(`${API_ROOT}/workflow/regenerate-candidate-plan`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({}),
  })
  const result = await parseJsonResponse(response)
  if (!response.ok) {
    throw new Error(result.message ?? '候选实验重新生成失败。')
  }
  return result
}

export async function fetchLiveSession(): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法读取会话状态。')
  }

  const response = await fetch(`${API_ROOT}/session`, {
    method: 'GET',
  })
  const result = (await parseJsonResponse(response)) as LiveWorkflowResponse
  if (!response.ok) {
    throw new Error(result.message ?? '会话状态读取失败。')
  }
  return result
}

export async function waitForLiveStage(options: {
  accept: (session: LiveWorkflowResponse) => boolean
  reject?: (session: LiveWorkflowResponse) => boolean
  timeoutMs?: number
  intervalMs?: number
}): Promise<LiveWorkflowResponse> {
  const { accept, reject, timeoutMs = 240000, intervalMs = 5000 } = options
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    const session = await fetchLiveSession()
    if (reject?.(session)) {
      throw new Error(session.message ?? '后台流程执行失败，请查看失败报告。')
    }
    if (accept(session)) {
      return session
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs))
  }

  throw new Error('后台生成超时，请到不确定性队列页刷新状态后重试。')
}

async function postUncertaintyRecovery(
  path: '/uncertainty/extend' | '/uncertainty/retry' | '/uncertainty/manual',
  payload: Record<string, unknown>,
): Promise<UncertaintyRecoveryResult> {
  if (!API_ROOT) {
    throw new Error('本地运行服务未配置，无法补足科学不确定性。')
  }

  const response = await fetch(`${API_ROOT}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  const result = (await parseJsonResponse(response)) as UncertaintyRecoveryResult
  if (!response.ok) {
    throw new Error(result.message ?? '科学不确定性补足失败。')
  }
  return result
}

export async function extendUncertaintyGeneration(
  targetCount = 6,
): Promise<UncertaintyRecoveryResult> {
  return postUncertaintyRecovery('/uncertainty/extend', { targetCount })
}

export async function retryUncertaintyGeneration(
  targetCount = 6,
): Promise<UncertaintyRecoveryResult> {
  return postUncertaintyRecovery('/uncertainty/retry', { targetCount })
}

export async function manualUncertaintySupplement(
  items: ManualUncertaintyItem[],
  targetCount?: number,
): Promise<UncertaintyRecoveryResult> {
  return postUncertaintyRecovery('/uncertainty/manual', {
    items,
    targetCount: targetCount ?? Math.max(items.length, 4),
  })
}
