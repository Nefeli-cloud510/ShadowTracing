const LOCAL_API_ORIGIN =
  typeof window !== 'undefined' && /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname)
    ? 'http://127.0.0.1:8765'
    : ''

const API_ROOT =
  typeof import.meta !== 'undefined'
    ? import.meta.env.VITE_WORKFLOW_API_BASE?.trim() ?? (LOCAL_API_ORIGIN ? `${LOCAL_API_ORIGIN}/api` : '')
    : ''

export interface StartWorkflowPayload {
  question: string
  knowledgeFiles: File[]
  dataFiles: File[]
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
    }>
  }
}

export interface LiveWorkflowResponse {
  status: string
  stage?: string
  message?: string
  question?: string
  runRoot?: string
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
  formData.append('model', payload.model ?? 'qwen-plus')
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
  for (const file of payload.dataFiles) {
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

export async function resetWorkflow(): Promise<LiveWorkflowResponse> {
  if (!API_ROOT) {
    return { status: 'idle' }
  }

  const response = await fetch(`${API_ROOT}/session/reset`, {
    method: 'POST',
  })
  const result = await parseJsonResponse(response)

  if (!response.ok) {
    throw new Error(result.message ?? '重置运行状态失败。')
  }

  return result
}

export async function analyzeQuestion(question: string, model = 'qwen-plus'): Promise<QuestionAnalysis> {
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
