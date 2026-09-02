import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  analyzeQuestion,
  inspectDataFiles,
  resetWorkflow,
  startWorkflow,
  submitRoundDecision,
  type DataInspectionResult,
  type QuestionAnalysis,
} from '../api/liveWorkflow'
import { PageTabs } from '../components/PageTabs'
import { StepConfirmDialog } from '../components/StepConfirmDialog'
import { useTimelineBundle } from '../hooks/useTimelineBundle'
import {
  clearDataDictionaryDraft,
  deriveVariableSelections,
  mergeDataDictionaryDraft,
  readDataDictionaryDraft,
  serializeDraftForApi,
  type DataDictionaryDraft,
  validateDataDictionaryDraft,
  writeDataDictionaryDraft,
} from '../utils/dataDictionaryDraft'
import {
  clearMissionControllerDraft,
  clearUploadFiles,
  loadUploadFiles,
  mergeSelectedFiles,
  notifyWorkspaceReset,
  persistUploadFiles,
  readMissionControllerDraft,
  WORKSPACE_RESET_EVENT,
  writeMissionControllerDraft,
} from '../utils/missionControllerPersistence'

export function MissionPage() {
  const navigate = useNavigate()
  const { data, loading, error, refresh } = useTimelineBundle()
  const mission = data?.viewModels.mission
  const processMonitor = data?.viewModels.processMonitor
  const [question, setQuestion] = useState('')
  const [knowledgeFiles, setKnowledgeFiles] = useState<string[]>([])
  const [dataFiles, setDataFiles] = useState<string[]>([])
  const [knowledgeUploads, setKnowledgeUploads] = useState<File[]>([])
  const [dataUploads, setDataUploads] = useState<File[]>([])
  const [submitted, setSubmitted] = useState(false)
  const [questionAnalysis, setQuestionAnalysis] = useState<QuestionAnalysis | null>(null)
  const [confirmedX, setConfirmedX] = useState('')
  const [confirmedY, setConfirmedY] = useState('')
  const [confirmedM, setConfirmedM] = useState('')
  const [questionType, setQuestionType] = useState<'forecasting' | 'scientific_inquiry'>('scientific_inquiry')
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [roundFeedback, setRoundFeedback] = useState('')
  const [roundDecision, setRoundDecision] = useState<'continue' | 'adjust' | 'stop'>('adjust')
  const [submittingFeedback, setSubmittingFeedback] = useState(false)
  const [backendError, setBackendError] = useState<string | null>(null)
  const [confirmStartOpen, setConfirmStartOpen] = useState(false)
  const [confirmRoundDecisionOpen, setConfirmRoundDecisionOpen] = useState(false)
  const [inspectingData, setInspectingData] = useState(false)
  const [latestInspection, setLatestInspection] = useState<DataInspectionResult | null>(null)
  const [dictionaryDraft, setDictionaryDraft] = useState<DataDictionaryDraft | null>(() => readDataDictionaryDraft())
  const [hydrating, setHydrating] = useState(true)

  useEffect(() => {
    if (!mission?.scientificQuestion) {
      return
    }
    setSubmitted(true)
  }, [mission?.scientificQuestion])

  useEffect(() => {
    if (!questionAnalysis) {
      return
    }
    setConfirmedX(questionAnalysis.x_variable ?? '')
    setConfirmedY(questionAnalysis.y_variable ?? '')
    setConfirmedM((questionAnalysis.m_candidates ?? []).join('，'))
    setQuestionType(questionAnalysis.question_type === 'forecasting' ? 'forecasting' : 'scientific_inquiry')
  }, [questionAnalysis])

  useEffect(() => {
    async function hydrateMissionController() {
      const persistedDraft = readMissionControllerDraft()
      const [storedKnowledgeUploads, storedDataUploads] = await Promise.all([
        loadUploadFiles('knowledge'),
        loadUploadFiles('data'),
      ])

      if (persistedDraft) {
        setQuestion(persistedDraft.question)
        setKnowledgeFiles(persistedDraft.knowledgeFiles)
        setDataFiles(persistedDraft.dataFiles)
        setSubmitted(persistedDraft.submitted)
        setQuestionAnalysis(persistedDraft.questionAnalysis)
        setConfirmedX(persistedDraft.confirmedX)
        setConfirmedY(persistedDraft.confirmedY)
        setConfirmedM(persistedDraft.confirmedM)
        setQuestionType(persistedDraft.questionType)
        setRoundFeedback(persistedDraft.roundFeedback)
        setRoundDecision(persistedDraft.roundDecision)
        setLatestInspection(persistedDraft.latestInspection)
      }

      if (storedKnowledgeUploads.length > 0) {
        setKnowledgeUploads(storedKnowledgeUploads)
        setKnowledgeFiles(storedKnowledgeUploads.map((file) => file.name))
      }

      if (storedDataUploads.length > 0) {
        setDataUploads(storedDataUploads)
        setDataFiles(storedDataUploads.map((file) => file.name))
      }

      setHydrating(false)
    }

    void hydrateMissionController()
  }, [])

  useEffect(() => {
    const handleWorkspaceReset = () => {
      setQuestion('')
      setKnowledgeFiles([])
      setDataFiles([])
      setKnowledgeUploads([])
      setDataUploads([])
      setSubmitted(false)
      setQuestionAnalysis(null)
      setConfirmedX('')
      setConfirmedY('')
      setConfirmedM('')
      setQuestionType('scientific_inquiry')
      setRoundFeedback('')
      setRoundDecision('adjust')
      setLatestInspection(null)
      setDictionaryDraft(null)
      setBackendError(null)
    }
    window.addEventListener(WORKSPACE_RESET_EVENT, handleWorkspaceReset)
    return () => window.removeEventListener(WORKSPACE_RESET_EVENT, handleWorkspaceReset)
  }, [])

  useEffect(() => {
    const syncDraft = () => setDictionaryDraft(readDataDictionaryDraft())
    window.addEventListener('focus', syncDraft)
    return () => window.removeEventListener('focus', syncDraft)
  }, [])

  useEffect(() => {
    if (hydrating) {
      return
    }
    writeMissionControllerDraft({
      question,
      knowledgeFiles,
      dataFiles,
      submitted,
      questionAnalysis,
      confirmedX,
      confirmedY,
      confirmedM,
      questionType,
      roundFeedback,
      roundDecision,
      latestInspection,
    })
  }, [
    confirmedM,
    confirmedX,
    confirmedY,
    dataFiles,
    hydrating,
    knowledgeFiles,
    latestInspection,
    question,
    questionAnalysis,
    questionType,
    roundDecision,
    roundFeedback,
    submitted,
  ])

  const dictionarySelections = useMemo(() => deriveVariableSelections(dictionaryDraft), [dictionaryDraft])

  useEffect(() => {
    if (dictionarySelections.xVariable) {
      setConfirmedX(dictionarySelections.xVariable)
    }
    if (dictionarySelections.yVariable) {
      setConfirmedY(dictionarySelections.yVariable)
    }
    if (dictionarySelections.mCandidates.length > 0) {
      setConfirmedM(dictionarySelections.mCandidates.join('，'))
    }
  }, [dictionarySelections.mCandidates, dictionarySelections.xVariable, dictionarySelections.yVariable])

  const existingDataSources = mission?.dataSources ?? []
  const resolvedX = dictionarySelections.xVariable || confirmedX.trim() || questionAnalysis?.x_variable?.trim() || ''
  const resolvedY = dictionarySelections.yVariable || confirmedY.trim() || questionAnalysis?.y_variable?.trim() || ''
  const resolvedM =
    dictionarySelections.mCandidates.length > 0
      ? dictionarySelections.mCandidates
      : confirmedM
          .split(/[，,、]/)
          .map((item) => item.trim())
          .filter(Boolean)
  const readyToStart = question.trim().length > 0 && dataUploads.length > 0 && resolvedX.length > 0 && resolvedY.length > 0
  const sessionStage = data?.snapshot.sessionStatus?.stage
  const sessionStatus = data?.snapshot.sessionStatus?.status
  const processStage = data?.snapshot.process?.current_stage
  const awaitingRoundDecision =
    processStage === 'awaiting_round_decision'
    || sessionStage === 'round_review_requested'
    || sessionStatus === 'awaiting_round_decision'

  const dialogueFeed = useMemo(() => {
    const feed = [
      {
        id: 'intro',
        role: 'agent',
        speaker: '中央控制智能体',
        content: '请先描述你的科学问题，我会继续引导你补齐知识库文件、数据文件与实验约束。',
      },
    ]

    if (submitted && question.trim()) {
      feed.push({
        id: 'question',
        role: 'user',
        speaker: '研究负责人',
        content: question.trim(),
      })
      feed.push({
        id: 'guide',
        role: 'agent',
        speaker: '中央控制智能体',
        content: '已记录科学问题。接下来我会先解析变量结构，再根据你上传的知识材料与数据文件启动真实闭环。',
      })
    }

    if (questionAnalysis) {
      feed.push({
        id: 'analysis',
        role: 'agent',
        speaker: '中央控制智能体',
        content: questionAnalysis.needs_confirmation
          ? questionAnalysis.clarification_question ?? '变量提取还不稳定，请人工确认核心解释变量与目标变量。'
          : `已识别核心解释变量为 ${resolvedX}，目标变量为 ${resolvedY}，问题类型为 ${questionType === 'forecasting' ? '预测型' : '科学机理型'}。`,
      })
    }

    return feed.concat((mission?.dialogueMessages ?? []).slice(0, 4))
  }, [mission?.dialogueMessages, question, questionAnalysis, questionType, resolvedX, resolvedY, submitted])

  async function handleKnowledgeUploadSelection(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    const merged = mergeSelectedFiles(knowledgeUploads, files)
    setKnowledgeUploads(merged)
    setKnowledgeFiles(merged.map((file) => file.name))
    await persistUploadFiles('knowledge', merged)
  }

  async function handleDataUploadSelection(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    const mergedFiles = mergeSelectedFiles(dataUploads, files)
    setDataFiles(mergedFiles.map((file) => file.name))
    setDataUploads(mergedFiles)
    await persistUploadFiles('data', mergedFiles)

    if (mergedFiles.length === 0) {
      setLatestInspection(null)
      setDictionaryDraft(null)
      clearDataDictionaryDraft()
      return
    }

    try {
      setInspectingData(true)
      setBackendError(null)
      const inspection = await inspectDataFiles(mergedFiles)
      const nextDraft = mergeDataDictionaryDraft(inspection, readDataDictionaryDraft())
      setLatestInspection(inspection)
      setDictionaryDraft(nextDraft)
      writeDataDictionaryDraft(nextDraft)
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : '实验数据表头解析失败。')
    } finally {
      setInspectingData(false)
    }
  }

  async function handleAnalyzeQuestion() {
    if (!question.trim() || analysisLoading) {
      return
    }
    try {
      setAnalysisLoading(true)
      setBackendError(null)
      setSubmitted(true)
      const analysis = await analyzeQuestion(question.trim())
      setQuestionAnalysis(analysis)
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : '科学问题解析失败。')
    } finally {
      setAnalysisLoading(false)
    }
  }

  async function handleStartWorkflow() {
    if (!readyToStart || starting) {
      return
    }

    try {
      setStarting(true)
      setBackendError(null)
      setSubmitted(true)
      const dictionaryValidationError = validateDataDictionaryDraft(dictionaryDraft)
      if (dictionaryValidationError) {
        throw new Error(dictionaryValidationError)
      }
      let analysis = questionAnalysis
      const hasManualVariables = resolvedX.length > 0 && resolvedY.length > 0
      if (!analysis && !hasManualVariables) {
        analysis = await analyzeQuestion(question.trim())
        setQuestionAnalysis(analysis)
      }
      await startWorkflow({
        question: question.trim(),
        knowledgeFiles: knowledgeUploads,
        dataFiles: dataUploads,
        rounds: 2,
        xVariable: resolvedX || analysis?.x_variable,
        yVariable: resolvedY || analysis?.y_variable,
        mCandidates: resolvedM.length > 0 ? resolvedM : analysis?.m_candidates,
        questionType,
        dataDictionaryConfig: dictionaryDraft ? serializeDraftForApi(dictionaryDraft) : undefined,
      })
      navigate('/workflow')
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : '真实闭环启动失败。')
    } finally {
      setStarting(false)
    }
  }

  async function handleResetSession() {
    try {
      setResetting(true)
      setBackendError(null)
      await resetWorkflow()
      setQuestion('')
      setKnowledgeFiles([])
      setDataFiles([])
      setKnowledgeUploads([])
      setDataUploads([])
      setSubmitted(false)
      setQuestionAnalysis(null)
      setConfirmedX('')
      setConfirmedY('')
      setConfirmedM('')
      setRoundFeedback('')
      setLatestInspection(null)
      setDictionaryDraft(null)
      clearDataDictionaryDraft()
      clearMissionControllerDraft()
      await clearUploadFiles()
      notifyWorkspaceReset()
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : '重置当前会话失败。')
    } finally {
      setResetting(false)
    }
  }

  async function handleSubmitRoundFeedback() {
    if (!awaitingRoundDecision || submittingFeedback) {
      return
    }
    try {
      setSubmittingFeedback(true)
      setBackendError(null)
      await submitRoundDecision({
        decision: roundDecision,
        humanFeedback: roundFeedback.trim() || undefined,
      })
      await refresh()
      if (roundDecision !== 'stop') {
        navigate('/approval')
      }
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : '整轮反馈提交失败。')
    } finally {
      setSubmittingFeedback(false)
    }
  }

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          <>
            <header className="workspace-page__header">
              <div>
                <span className="timeline-header__eyebrow">Central Controller</span>
                  <h1>智能体交互控制台</h1>
                  <p>以一问一答方式推进真实闭环：解析问题、确认变量、上传数据、启动实验，并在每轮结束后接收人工反馈。</p>
              </div>

              <div className="detail-page__meta">
                <div className="status-chip">
                  <span>目标变量</span>
                  <strong>{mission?.target ?? '--'}</strong>
                </div>
                <div className="status-chip">
                  <span>当前轮次</span>
                  <strong>{data?.viewModels.currentRoundNumber ?? '--'}</strong>
                </div>
                <div className="status-chip">
                  <span>核心指标</span>
                  <strong>{mission?.metrics[0] ?? '--'}</strong>
                </div>
              </div>
            </header>

            {hydrating ? <div className="timeline-empty-state">正在恢复当前工作区输入与上传文件…</div> : null}
            {loading ? <div className="timeline-empty-state">正在连接真实运行服务并同步当前状态…</div> : null}
            {error ? <div className="timeline-empty-state timeline-empty-state--error">{error}</div> : null}

            <section className="detail-card detail-card--wide">
              <div className="controller-layout">
                <aside className="controller-sidebar">
                  <strong>核心步骤</strong>
                  <ol className="controller-sidebar__list">
                    <li>输入科学问题</li>
                    <li>上传知识材料</li>
                    <li>上传实验数据</li>
                    <li>配置数据字典</li>
                    <li>解析变量结构</li>
                    <li>启动真实闭环</li>
                    <li>记录整轮反馈</li>
                    <li>推进下一轮或停止</li>
                  </ol>
                </aside>

                <div className="controller-conversation">
                  <div className="dialogue-thread dialogue-thread--dense">
                    {dialogueFeed.map((item) => (
                      <article
                        key={item.id}
                        className={[
                          'dialogue-bubble',
                          item.role === 'user'
                            ? 'dialogue-bubble--user'
                            : item.role === 'agent'
                              ? 'dialogue-bubble--agent'
                              : 'dialogue-bubble--system',
                        ].join(' ')}
                      >
                        <div className="dialogue-bubble__header">
                          <strong>{item.speaker}</strong>
                        </div>
                        <p>{item.content}</p>
                      </article>
                    ))}
                  </div>

                  <div className="controller-input">
                    <label className="controller-input__field">
                      <span>科学问题</span>
                      <textarea
                        value={question}
                        onChange={(event) => setQuestion(event.target.value)}
                        placeholder="请输入本次要研究的科学问题，系统会基于你的输入发起真实推理与实验规划。"
                        rows={4}
                      />
                    </label>

                    <div className="controller-input__actions">
                      <button
                        type="button"
                        className="detail-link detail-link--button"
                        onClick={() => {
                          setSubmitted(true)
                          setBackendError(null)
                        }}
                      >
                        记录问题
                      </button>
                      <button
                        type="button"
                        className="detail-link detail-link--button detail-link--accent"
                        onClick={() => void handleAnalyzeQuestion()}
                        disabled={!question.trim() || analysisLoading}
                      >
                        {analysisLoading ? '解析中…' : '让 LLM 解析变量'}
                      </button>
                    </div>

                    <div className="upload-zone-grid">
                      <label className="upload-zone">
                        <span>知识材料</span>
                        <input
                          type="file"
                          multiple
                          onChange={(event) =>
                            void handleKnowledgeUploadSelection(event)
                          }
                        />
                        <div className="upload-zone__hint">
                          {knowledgeFiles.length > 0
                            ? knowledgeFiles.join('，')
                            : '可选上传文献摘要、项目背景、知识索引等材料'}
                        </div>
                      </label>

                      <label className="upload-zone">
                        <span>实验数据</span>
                        <input type="file" multiple onChange={(event) => void handleDataUploadSelection(event)} />
                        <div className="upload-zone__hint">
                          {dataFiles.length > 0
                            ? `${dataFiles.join('，')} ${inspectingData ? '· 正在解析表头…' : '· 已自动解析表头'}`
                            : '必须上传真实实验数据文件；上传后会自动解析全部表头列名'}
                        </div>
                      </label>
                    </div>

                    <article className="dialogue-summary__card">
                      <strong>数据字典配置</strong>
                      <p>
                        {dictionaryDraft
                          ? `已识别 ${dictionaryDraft.fields.length} 个表头字段，请补充物理量释义并划分变量类别。`
                          : '请先上传实验数据，系统会自动解析表头并生成待配置的数据字典。'}
                      </p>
                      <div className="controller-input__actions">
                        <button
                          type="button"
                          className="detail-link detail-link--button"
                          onClick={() => navigate('/data-dictionary')}
                          disabled={!dictionaryDraft}
                        >
                          数据字典配置
                        </button>
                      </div>
                    </article>

                    <div className="workspace-page__grid">
                      <article className="dialogue-summary__card">
                        <strong>核心解释变量</strong>
                        <input
                          className="controller-inline-input"
                          value={confirmedX}
                          onChange={(event) => setConfirmedX(event.target.value)}
                          placeholder="由 LLM 自动提取，必要时人工确认"
                        />
                      </article>
                      <article className="dialogue-summary__card">
                        <strong>目标变量</strong>
                        <input
                          className="controller-inline-input"
                          value={confirmedY}
                          onChange={(event) => setConfirmedY(event.target.value)}
                          placeholder="由 LLM 自动提取，必要时人工确认"
                        />
                      </article>
                      <article className="dialogue-summary__card">
                        <strong>候选中介因素</strong>
                        <input
                          className="controller-inline-input"
                          value={confirmedM}
                          onChange={(event) => setConfirmedM(event.target.value)}
                          placeholder="可选，使用逗号分隔"
                        />
                      </article>
                    </div>

                    <article className="dialogue-summary__card">
                      <strong>真实解析反馈</strong>
                      <p>{questionAnalysis?.rationale ?? '尚未触发问题解析。'}</p>
                      <p>
                        当前识别结果：{resolvedX || '--'} / {resolvedY || '--'} /{' '}
                        {questionType === 'forecasting' ? '预测型问题' : '科学机理问题'}
                      </p>
                      {dictionaryDraft ? (
                        <p>
                          当前数据字典：核心解释变量 {dictionarySelections.xVariable || '--'}，目标变量{' '}
                          {dictionarySelections.yVariable || '--'}，候选中介因素 {dictionarySelections.mCandidates.join('，') || '--'}
                        </p>
                      ) : null}
                    </article>

                    {backendError ? <div className="timeline-empty-state timeline-empty-state--error">{backendError}</div> : null}

                    <div className="controller-input__actions">
                      <button
                        type="button"
                        className="detail-link detail-link--button"
                        onClick={() => void handleResetSession()}
                      >
                        {resetting ? '正在清空…' : '清零记忆'}
                      </button>
                      <button
                        type="button"
                        className="detail-link detail-link--button detail-link--accent"
                        onClick={() => setConfirmStartOpen(true)}
                        disabled={!readyToStart || starting}
                      >
                        {starting ? '真实链路启动中…' : '启动真实实验'}
                      </button>
                    </div>

                    <article className="dialogue-summary__card">
                      <strong>整轮运行反馈</strong>
                      <textarea
                        value={roundFeedback}
                        onChange={(event) => setRoundFeedback(event.target.value)}
                        placeholder="在一轮实验结束后，可在这里输入人工反馈、方向调整意见或停止理由。"
                        rows={4}
                      />
                      <div className="controller-input__actions">
                        <select
                          className="controller-inline-input"
                          value={roundDecision}
                          onChange={(event) => setRoundDecision(event.target.value as 'continue' | 'adjust' | 'stop')}
                        >
                          <option value="continue">进入下一轮</option>
                          <option value="adjust">调整后进入下一轮</option>
                          <option value="stop">停止闭环</option>
                        </select>
                        <button
                          type="button"
                          className="detail-link detail-link--button"
                          onClick={() => setConfirmRoundDecisionOpen(true)}
                          disabled={!awaitingRoundDecision || submittingFeedback}
                        >
                          {submittingFeedback ? '提交中…' : '提交整轮反馈'}
                        </button>
                      </div>
                    </article>
                  </div>
                </div>

                <aside className="controller-status">
                  <article className="dialogue-summary__card">
                    <strong>当前科学问题</strong>
                    <p>{question.trim() || mission?.scientificQuestion || '尚未录入'}</p>
                  </article>
                  <article className="dialogue-summary__card">
                    <strong>真实调用状态</strong>
                    <p>{processMonitor?.currentPhase ?? '待启动'} / {processMonitor?.currentStage ?? '待更新'}</p>
                    <p>当前步骤：{processMonitor?.currentStep ?? '--'}</p>
                  </article>
                  <article className="dialogue-summary__card">
                    <strong>知识材料</strong>
                    <p>{knowledgeFiles.length > 0 ? knowledgeFiles.join('，') : '本轮尚未上传，可按需补充。'}</p>
                  </article>
                  <article className="dialogue-summary__card">
                    <strong>实验数据</strong>
                    <p>
                      {dataFiles.length > 0
                        ? dataFiles.join('，')
                        : existingDataSources.map((source) => source.id).join('，') || '本轮尚未上传'}
                    </p>
                  </article>
                  <article className="dialogue-summary__card">
                    <strong>数据字典状态</strong>
                    <p>
                      {dictionaryDraft
                        ? `表头 ${dictionaryDraft.fields.length} 项，核心解释变量 ${dictionarySelections.xVariable || '--'}，目标变量 ${dictionarySelections.yVariable || '--'}`
                        : '尚未生成数据字典配置。'}
                    </p>
                    <p>{latestInspection ? `已解析 ${latestInspection.tables.length} 份数据表。` : '上传实验数据后自动生成。'}</p>
                  </article>
                  <article className="dialogue-summary__card">
                    <strong>启动条件</strong>
                    <ul className="detail-list">
                      <li>科学问题：{question.trim() ? '已填写' : '未填写'}</li>
                      <li>变量提取：{resolvedX && resolvedY ? '已确认' : '待确认'}</li>
                      <li>知识材料：{knowledgeFiles.length > 0 ? '已上传' : '可选'}</li>
                      <li>实验数据：{dataFiles.length > 0 ? '已上传' : '待上传'}</li>
                    </ul>
                  </article>
                </aside>
              </div>
            </section>
          </>
        </section>
        <StepConfirmDialog
          open={confirmStartOpen}
          title="是否进入科学假设生成过程？"
          message="系统将基于当前科学问题、变量绑定和上传数据，初始化真实闭环并进入科学假设生成与候选实验规划。"
          confirmLabel="确认启动"
          onCancel={() => setConfirmStartOpen(false)}
          onConfirm={() => {
            setConfirmStartOpen(false)
            void handleStartWorkflow()
          }}
        />
        <StepConfirmDialog
          open={confirmRoundDecisionOpen}
          title={
            roundDecision === 'stop'
              ? '是否停止当前闭环？'
              : roundDecision === 'continue'
                ? '是否进入下一轮闭环？'
                : '是否按当前反馈调整后进入下一轮？'
          }
          message={
            roundDecision === 'stop'
              ? '系统将结束当前闭环，并固化本轮状态与产物。'
              : roundDecision === 'continue'
                ? '系统将根据当前整轮反馈继续生成下一轮假设与候选实验。'
                : '系统将携带当前人工反馈，重新规划下一轮假设与候选实验。'
          }
          confirmLabel={roundDecision === 'stop' ? '确认停止' : '确认提交'}
          onCancel={() => setConfirmRoundDecisionOpen(false)}
          onConfirm={() => {
            setConfirmRoundDecisionOpen(false)
            void handleSubmitRoundFeedback()
          }}
        />
      </div>
    </div>
  )
}
