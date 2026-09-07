import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CandidateExperimentTable } from '../components/CandidateExperimentTable'
import { PageTabs } from '../components/PageTabs'
import { StepConfirmDialog } from '../components/StepConfirmDialog'
import { UncertaintyQueueList } from '../components/UncertaintyQueueList'
import {
  extendUncertaintyGeneration,
  manualUncertaintySupplement,
  regenerateCandidatePlan,
  retryUncertaintyGeneration,
  type ManualUncertaintyItem,
} from '../api/liveWorkflow'
import { useTimelineBundle } from '../hooks/useTimelineBundle'
import { filterSelectableCandidateExperiments } from '../utils/experimentValidation'
import { toDisplayText } from '../data/realStateLoader'

type FilterMode = 'all' | 'active' | 'resolved'
type RecoveryKind = 'extend' | 'retry' | 'manual' | null

export function UncertaintyPage() {
  const navigate = useNavigate()
  const { data, loading, error, refreshing, refresh } = useTimelineBundle()
  const currentRoundNumber =
    Number(data?.viewModels.currentRoundNumber ?? data?.snapshot.process?.current_round ?? 0) || 0
  const candidateRound =
    Number(data?.snapshot.candidateExperiments?.round ?? currentRoundNumber) || currentRoundNumber
  const [filterMode, setFilterMode] = useState<FilterMode>('all')
  const [confirmNextOpen, setConfirmNextOpen] = useState(false)
  const [recoveryPending, setRecoveryPending] = useState<RecoveryKind>(null)
  const [manualOpen, setManualOpen] = useState(false)
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null)
  const [recoveryError, setRecoveryError] = useState<string | null>(null)
  const [candidateRegenPending, setCandidateRegenPending] = useState(false)
  const [candidateRegenMessage, setCandidateRegenMessage] = useState<string | null>(null)
  const [candidateRegenError, setCandidateRegenError] = useState<string | null>(null)
  const [manualItem, setManualItem] = useState<ManualUncertaintyItem>({
    question: '',
    description: '',
    priority: 'medium',
    relatedHypotheses: [],
    features: [],
  })
  const selectableCandidates = useMemo(
    () =>
      filterSelectableCandidateExperiments<any>(
        (data?.snapshot.candidateExperiments?.candidates ?? []).filter(
          (candidate: any) => Number(candidate.round_id ?? candidateRound) === currentRoundNumber,
        ),
      ),
    [data?.snapshot.candidateExperiments?.candidates, currentRoundNumber, candidateRound],
  )
  const roundUncertainties = useMemo(() => {
    const fallbackRound =
      Number(data?.snapshot.uncertainties?.current_round ?? currentRoundNumber) || currentRoundNumber
    return (data?.snapshot.uncertainties?.records ?? []).filter((item: any) =>
      Number(item.created_at_round ?? item.current_round ?? fallbackRound) === currentRoundNumber,
    )
  }, [data?.snapshot.uncertainties?.records, currentRoundNumber])
  const displayText = useMemo(
    () => (text?: string) => toDisplayText(text ?? '', data?.snapshot.plannerInput?.data_dictionary_summary),
    [data?.snapshot.plannerInput?.data_dictionary_summary],
  )
  const hypothesisLabel = useMemo(() => {
    const map = new Map<string, string>()
    for (const node of data?.snapshot.hypothesisTree?.nodes ?? []) {
      const label = node.display_hypothesis_id || (node.level ? `H${node.level}` : '')
      if (node.hypothesis_id && label) {
        map.set(node.hypothesis_id, label)
      }
    }
    return (id?: string) => {
      if (!id) {
        return '未关联假设'
      }
      return map.get(id) || (id.startsWith('H') ? id : 'H?')
    }
  }, [data?.snapshot.hypothesisTree?.nodes])
  const resolvingExperimentMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const candidate of selectableCandidates) {
      for (const uncertaintyId of candidate.related_uncertainties ?? []) {
        if (candidate.experiment_id && !map.has(uncertaintyId)) {
          map.set(uncertaintyId, candidate.experiment_id)
        }
      }
    }
    return map
  }, [selectableCandidates])
  const activeRecordCount = useMemo(
    () =>
      roundUncertainties.filter((item: any) => {
        const status = String(item.resolution_status ?? item.status ?? '')
        return !status.includes('resolved') && !status.includes('deprecated')
      }).length,
    [roundUncertainties],
  )
  const insufficientQueue = activeRecordCount < 4
  const modelName = String(data?.snapshot.sessionStatus?.model ?? 'qwen3.8-flash')
  const sessionStatus = String(data?.snapshot.sessionStatus?.status ?? '')
  const sessionStage = String(data?.snapshot.sessionStatus?.stage ?? '')
  const sessionMessage = data?.snapshot.sessionStatus?.message ?? ''
  const generationActive = useMemo(() => {
    const phase = String(data?.snapshot.process?.current_phase ?? '')
    const haystack = `${sessionStatus} ${sessionStage} ${phase}`.toLowerCase()
    return (
      haystack.includes('generat') ||
      haystack.includes('mining') ||
      haystack.includes('recover') ||
      haystack.includes('rebuild')
    )
  }, [sessionStatus, sessionStage, data?.snapshot.process?.current_phase])

  useEffect(() => {
    if (!candidateRegenError && !candidateRegenMessage) {
      return
    }
    if (sessionStatus === 'awaiting_approval' && sessionStage === 'approval_pending') {
      setCandidateRegenError(null)
      setCandidateRegenMessage(sessionMessage || '候选实验已重新生成，等待审批。')
    } else if (sessionStatus === 'failed') {
      setCandidateRegenError(null)
      setCandidateRegenMessage(null)
    }
  }, [candidateRegenError, candidateRegenMessage, sessionMessage, sessionStage, sessionStatus])

  const records = useMemo(() => {
    return roundUncertainties
      .filter((item: any) => {
        if (filterMode === 'all') {
          return true
        }
        if (filterMode === 'active') {
          return !String(item.resolution_status ?? item.status ?? '').includes('resolved')
        }
        return String(item.resolution_status ?? item.status ?? '').includes('resolved')
      })
      .map((item: any) => ({
        ...item,
        resolving_experiment:
          item.resolution_status === 'resolved'
            ? item.resolving_experiment
            : resolvingExperimentMap.get(item.uncertainty_id) ?? item.resolving_experiment,
      }))
      .slice(0, 10)
  }, [roundUncertainties, filterMode, resolvingExperimentMap])

  async function runRecovery(kind: 'extend' | 'retry') {
    setRecoveryPending(kind)
    setRecoveryError(null)
    setRecoveryMessage(null)
    try {
      const result = kind === 'extend' ? await extendUncertaintyGeneration() : await retryUncertaintyGeneration()
      setRecoveryMessage(result.message ?? `已通过${kind === 'extend' ? '扩展' : '重试'}补充不确定性。`)
      await refresh()
    } catch (err) {
      setRecoveryError(err instanceof Error ? err.message : '不确定性补足失败。')
    } finally {
      setRecoveryPending(null)
    }
  }

  async function submitManualSupplement() {
    if (!manualItem.question.trim()) {
      setRecoveryError('人工补充至少需要填写不确定性问题。')
      return
    }
    setRecoveryPending('manual')
    setRecoveryError(null)
    setRecoveryMessage(null)
    try {
      const result = await manualUncertaintySupplement([
        {
          ...manualItem,
          question: manualItem.question.trim(),
          description: manualItem.description?.trim() || undefined,
        },
      ])
      setRecoveryMessage(result.message ?? '人工补充已写入不确定性队列。')
      setManualItem({ question: '', description: '', priority: 'medium', relatedHypotheses: [], features: [] })
      setManualOpen(false)
      await refresh()
    } catch (err) {
      setRecoveryError(err instanceof Error ? err.message : '人工补充写入失败。')
    } finally {
      setRecoveryPending(null)
    }
  }

  async function regenerateCandidates() {
    setCandidateRegenPending(true)
    setCandidateRegenError(null)
    setCandidateRegenMessage(null)
    try {
      const result = await regenerateCandidatePlan()
      setCandidateRegenMessage(result.message ?? '正在由 LLM 重新生成候选实验。')
      await refresh()
    } catch (err) {
      setCandidateRegenError(err instanceof Error ? err.message : '候选实验重新生成失败。')
    } finally {
      setCandidateRegenPending(false)
    }
  }

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取不确定性记录…</div>
          ) : error ? (
            <div className="timeline-empty-state timeline-empty-state--error">{error}</div>
          ) : (
            <>
              <header className="workspace-page__header">
                <div>
                  <span className="timeline-header__eyebrow">Uncertainty Identification</span>
                  <h1>不确定性驱动的候选实验</h1>
                  <p>在假设生成和科学质询之后，系统将核心分歧收敛为不确定性列表，并驱动候选实验生成。</p>
                </div>
                <div className="detail-page__meta">
                  <button
                    type="button"
                    className="detail-link detail-link--button detail-link--accent"
                    disabled={candidateRegenPending || recoveryPending !== null || generationActive}
                    onClick={() => void regenerateCandidates()}
                  >
                    {candidateRegenPending ? '重新生成中…' : generationActive ? '等待生成完成' : '重新生成'}
                  </button>
                  <button
                    type="button"
                    className="detail-link detail-link--button"
                    onClick={() => void refresh()}
                  >
                    {refreshing ? '刷新中…' : '刷新'}
                  </button>
                  <div className="status-chip">
                    <span>运行模型</span>
                    <strong>{modelName}</strong>
                  </div>
                </div>
              </header>

              {(candidateRegenMessage || candidateRegenError) && (
                <p
                  className={
                    candidateRegenError
                      ? 'uncertainty-recovery-bar__error candidate-regen-note'
                      : 'uncertainty-recovery-bar__message candidate-regen-note'
                  }
                >
                  {candidateRegenError ??
                    (candidateRegenPending || generationActive
                      ? `${candidateRegenMessage} 生成大约需要5-15分钟，请耐心等待。`
                      : candidateRegenMessage)}
                </p>
              )}

              <section className="detail-card detail-card--wide">
                <div className="uncertainty-filter-bar">
                  <strong>不确定性驱动的候选实验</strong>
                  <div className="detail-links">
                    <button type="button" className="detail-link detail-link--button" onClick={() => setFilterMode('all')}>
                      全部
                    </button>
                    <button type="button" className="detail-link detail-link--button" onClick={() => setFilterMode('active')}>
                      活跃
                    </button>
                    <button type="button" className="detail-link detail-link--button" onClick={() => setFilterMode('resolved')}>
                      已解决
                    </button>
                  </div>
                </div>

                {insufficientQueue && (
                  <div className="uncertainty-recovery-bar">
                    <div className="uncertainty-recovery-bar__copy">
                      <strong>当前有效不确定性 {activeRecordCount} 条</strong>
                      <span>低于最少 4 条，可补充后继续生成候选实验。</span>
                    </div>
                    <div className="detail-links">
                      <button
                        type="button"
                        className="detail-link detail-link--button detail-link--accent"
                        disabled={recoveryPending !== null || generationActive}
                        onClick={() => void runRecovery('extend')}
                      >
                        {generationActive ? '生成中，请勿重复点击' : recoveryPending === 'extend' ? '扩展中…' : '扩展生成'}
                      </button>
                      <button
                        type="button"
                        className="detail-link detail-link--button"
                        disabled={recoveryPending !== null || generationActive}
                        onClick={() => void runRecovery('retry')}
                      >
                        {generationActive ? '等待生成完成' : recoveryPending === 'retry' ? '重试中…' : '重试生成'}
                      </button>
                      <button
                        type="button"
                        className="detail-link detail-link--button"
                        disabled={recoveryPending !== null}
                        onClick={() => {
                          setRecoveryError(null)
                          setManualOpen((open) => !open)
                        }}
                      >
                        人工补充
                      </button>
                    </div>
                    {recoveryMessage && <p className="uncertainty-recovery-bar__message">{recoveryMessage}</p>}
                    {recoveryError && <p className="uncertainty-recovery-bar__error">{recoveryError}</p>}
                    {manualOpen && (
                      <div className="uncertainty-manual-fields">
                        <input
                          value={manualItem.question}
                          placeholder="不确定性问题"
                          onChange={(event) =>
                            setManualItem((current) => ({ ...current, question: event.target.value }))
                          }
                        />
                        <textarea
                          value={manualItem.description ?? ''}
                          placeholder="补充说明（可选）"
                          onChange={(event) =>
                            setManualItem((current) => ({ ...current, description: event.target.value }))
                          }
                        />
                        <div className="uncertainty-manual-fields__actions">
                          <select
                            value={manualItem.priority}
                            onChange={(event) =>
                              setManualItem((current) => ({
                                ...current,
                                priority: (event.target.value as ManualUncertaintyItem['priority']),
                              }))
                            }
                          >
                            <option value="low">低优先级</option>
                            <option value="medium">中优先级</option>
                            <option value="high">高优先级</option>
                          </select>
                          <button
                            type="button"
                            className="detail-link detail-link--button detail-link--accent"
                            disabled={recoveryPending === 'manual'}
                            onClick={() => void submitManualSupplement()}
                          >
                            {recoveryPending === 'manual' ? '写入中…' : '提交补充'}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                <UncertaintyQueueList
                  records={records}
                  displayText={displayText}
                  hypothesisLabel={hypothesisLabel}
                  candidateLimit={Number(data?.snapshot.task?.payload?.constraints?.max_experiments_per_round ?? 6)}
                />
              </section>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Derivation Flow</span>
                <h2>不确定性驱动的候选实验生成报告</h2>
                <CandidateExperimentTable
                  candidates={selectableCandidates}
                  treeNodes={data?.snapshot.hypothesisTree?.nodes ?? []}
                  uncertaintyRecords={roundUncertainties}
                  displayText={displayText}
                />
              </section>

              <div className="workspace-page__grid">
                <section className="detail-card">
                  <span className="detail-card__eyebrow">Next Step</span>
                  <h2>进入候选实验审批</h2>
                  <p>确认不确定性后，实验规划者会围绕这些分歧生成候选实验，并交由人类 PI 审批。</p>
                  <div className="detail-links">
                    <button
                      type="button"
                      className="detail-link detail-link--button detail-link--accent"
                      onClick={() => setConfirmNextOpen(true)}
                    >
                      进入候选实验审批
                    </button>
                  </div>
                </section>
              </div>
            </>
          )}
        </section>
        <StepConfirmDialog
          open={confirmNextOpen}
          title="是否进入候选实验审批过程？"
          message="系统将展示当前候选实验的综合价值，并等待人工 PI 做出批准、修改或重选决策。"
          confirmLabel="进入审批"
          onCancel={() => setConfirmNextOpen(false)}
          onConfirm={() => navigate('/approval')}
        />
      </div>
    </div>
  )
}
