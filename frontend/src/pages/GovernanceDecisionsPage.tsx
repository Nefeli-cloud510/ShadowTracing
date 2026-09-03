import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { submitApprovalAction } from '../api/liveWorkflow'
import { ApprovalOverlay } from '../components/ApprovalOverlay'
import { PageTabs } from '../components/PageTabs'
import { StepConfirmDialog } from '../components/StepConfirmDialog'
import { useTimelineBundle } from '../hooks/useTimelineBundle'
import { filterSelectableCandidateExperiments, getExperimentValidationSnapshot } from '../utils/experimentValidation'

function formatDelta(before?: number, after?: number) {
  return `从 ${Number(before ?? 0).toFixed(3)} 调整到 ${Number(after ?? 0).toFixed(3)}`
}

export function GovernanceDecisionsPage() {
  const navigate = useNavigate()
  const { data, loading, error, refresh } = useTimelineBundle()
  const governance = data?.viewModels.governance
  const approvalOverlay = data?.viewModels.approvalOverlay
  const candidateRelations: any[] = filterSelectableCandidateExperiments(data?.snapshot.candidateExperiments?.candidates ?? [])
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<{
    action: 'approve' | 'modify' | 'reject' | 'pause'
    payload: { candidateId?: string; humanNotes?: string }
    title: string
    message: string
    confirmLabel: string
  } | null>(null)

  async function submitAction(
    action: 'approve' | 'modify' | 'reject' | 'pause',
    payload: { candidateId?: string; humanNotes?: string },
  ) {
    try {
      setActionBusy(true)
      setActionError(null)
      const result = await submitApprovalAction({
        action,
        candidateId: payload.candidateId ?? approvalOverlay?.recommendation.candidateId,
        humanNotes: payload.humanNotes,
      })
      await refresh()
      if (action === 'approve' || action === 'modify') {
        navigate('/execution')
      } else if (result.stage === 'approval_pending' || result.status === 'awaiting_approval') {
        navigate('/approval')
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '审批动作提交失败。')
    } finally {
      setActionBusy(false)
    }
  }

  async function queueApprovalAction(
    action: 'approve' | 'modify' | 'reject' | 'pause',
    payload: { candidateId?: string; humanNotes?: string },
  ) {
    const candidateId = payload.candidateId ?? approvalOverlay?.recommendation.candidateId ?? '当前推荐实验'
    const candidatePreview = candidateRelations.find((item: any) => item.experiment_id === candidateId)
    const validation = getExperimentValidationSnapshot(candidatePreview)
    const treatmentVariables = validation.treatmentVariables.join('、') || '待系统生成'
    const controlVariables = validation.controlVariables.join('、') || '待系统生成'
    const isBaselineExperiment = validation.experimentMode === 'baseline'
    const hasFeatureDifference = validation.hasFeatureDifference
    const scientificQuestion = candidatePreview?.scientific_question ?? candidatePreview?.purpose ?? '当前实验计划将围绕关键不确定性推进。'
    const contentMap = {
      approve: {
        title: '是否批准当前实验并进入执行？',
        message: isBaselineExperiment
          ? `实验 ${candidateId} 计划预览：${scientificQuestion}；该方案为基线实验，采用单组配置；基线变量：${treatmentVariables}；确认后系统将生成执行协议并自动进入实验执行页面。`
          : `实验 ${candidateId} 计划预览：${scientificQuestion}；对照组变量：${controlVariables}；实验组变量：${treatmentVariables}；变量差异校验：${hasFeatureDifference ? '通过' : '未通过'}；确认后系统将生成执行协议并自动进入实验执行页面。`,
        confirmLabel: '确认批准',
      },
      modify: {
        title: '是否按修改意见继续审批？',
        message: `实验 ${candidateId} 将带着你的修改意见继续推进；当前计划：${scientificQuestion}；实验组变量：${treatmentVariables}。确认后系统将重新写入协议并自动进入实验执行页面。`,
        confirmLabel: '确认修改',
      },
      reject: {
        title: '是否拒绝当前实验并返回重选？',
        message: `系统将拒绝 ${candidateId}，并回到候选实验重选流程。`,
        confirmLabel: '确认拒绝',
      },
      pause: {
        title: '是否暂停当前审批流程？',
        message: '系统将暂停当前候选实验审批，等待后续人工继续处理。',
        confirmLabel: '确认暂停',
      },
    } as const

    setPendingAction({
      action,
      payload,
      ...contentMap[action],
    })
  }

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取治理与决策状态…</div>
          ) : error || !governance ? (
            <div className="timeline-empty-state timeline-empty-state--error">
              {error ?? '治理与决策数据不可用。'}
            </div>
          ) : (
            <>
              {approvalOverlay ? (
                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Inline Approval</span>
                  <h2>页内审批操作</h2>
                  <ApprovalOverlay
                    data={approvalOverlay}
                    open
                    inline
                    onClose={() => undefined}
                    onAction={queueApprovalAction}
                    busy={actionBusy}
                  />
                </section>
              ) : null}

              <header className="workspace-page__header">
                <div>
                  <span className="timeline-header__eyebrow">Approval</span>
                  <h1>批准实验决策</h1>
                  <p>突出当前最优候选实验的综合价值，并由人类 PI 做出是否采纳的判断。</p>
                </div>

                <div className="detail-page__meta">
                  <div className="status-chip">
                    <span>待审批实验</span>
                    <strong>{governance.pendingApproval?.candidateId ?? '--'}</strong>
                  </div>
                  <div className="status-chip">
                    <span>当前阶段</span>
                    <strong>{governance.processSummary.currentPhase ?? '--'}</strong>
                  </div>
                  <div className="status-chip">
                    <span>当前步骤</span>
                    <strong>{governance.processSummary.currentStep ?? '--'}</strong>
                  </div>
                </div>
              </header>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Uncertainty Mapping</span>
                <h2>不确定性到候选实验的推导关系</h2>
                <div className="record-list">
                  {candidateRelations.map((candidate: any) => (
                    <article key={candidate.experiment_id} className="record-card">
                      {(() => {
                        const validation = getExperimentValidationSnapshot(candidate)
                        return (
                          <>
                      <div className="record-card__header">
                        <strong>{candidate.experiment_id}</strong>
                        <span>{candidate.related_uncertainties?.length ? '已建立关联' : '基线/补位实验'}</span>
                      </div>
                      <p>{candidate.scientific_question ?? candidate.purpose ?? '暂无实验说明'}</p>
                      <p>
                        关联不确定性：
                        {candidate.related_uncertainties?.length
                          ? candidate.related_uncertainties.join('，')
                          : '当前为基线或补位候选实验，不直接承接上游不确定性。'}
                      </p>
                      <p>
                        实验模式：
                        {validation.experimentMode === 'baseline' ? '基线实验（单组）' : '区分性对照实验'}
                      </p>
                      <p>
                        对照组变量：
                        {validation.experimentMode === 'baseline'
                          ? '不设置对照组'
                          : validation.controlVariables.length > 0
                            ? validation.controlVariables.join('、')
                            : '未配置'}
                      </p>
                      <p>实验组变量：{validation.treatmentVariables.length > 0 ? validation.treatmentVariables.join('、') : '未配置'}</p>
                      <p>
                        差异校验：
                        {validation.experimentMode === 'baseline'
                          ? '基线实验跳过对照差异校验'
                          : validation.hasFeatureDifference
                            ? '已通过'
                            : '未通过，应拦截'}
                      </p>
                          </>
                        )
                      })()}
                    </article>
                  ))}
                </div>
              </section>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Candidate Matrix</span>
                <h2>当前候选实验综合价值</h2>
                <div className="approval-candidate-strip">
                  {approvalOverlay?.candidates.map((candidate) => (
                    <article
                      key={candidate.experimentId}
                      className={`approval-candidate-card ${candidate.recommended ? 'approval-candidate-card--recommended' : ''}`}
                    >
                      <div className="approval-candidate-card__header">
                        <strong>{candidate.experimentId}</strong>
                        {candidate.recommended ? <span>最优</span> : null}
                      </div>
                      <div className="approval-candidate-card__utility">{candidate.utility.toFixed(3)}</div>
                      <div className="approval-candidate-card__metrics">
                        <span>IG {candidate.informationGain.toFixed(3)}</span>
                        <span>PG {candidate.performanceGain.toFixed(3)}</span>
                        <span>Risk {candidate.risk.toFixed(3)}</span>
                        <span>Cost {candidate.cost.toFixed(3)}</span>
                      </div>
                    </article>
                  ))}
                </div>
              </section>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Approval Comparison</span>
                <h2>批准实验决策</h2>
                <div className="approval-compare-grid">
                  {governance.approvalComparisons.map((item) => (
                    <article key={`approval-${item.roundNumber}`} className="approval-compare-card">
                      <div className="approval-compare-card__header">
                        <strong>Round {item.roundNumber}</strong>
                        <span>{item.review?.experimentId || item.approved?.candidateId || item.requested.candidateId || '--'}</span>
                      </div>
                      <div className="approval-side-by-side">
                        <section className="approval-side-by-side__panel">
                          <span className="approval-compare-card__label">候选实验</span>
                          <strong>{item.requested.candidateId || '--'}</strong>
                          <p>{item.requested.summary}</p>
                          <div className="approval-compare-card__meta">
                            <span>U(E): {item.requested.utilityScore.toFixed(3)}</span>
                          </div>
                          <div className="approval-metric-grid">
                            <span>IG {item.requested.metrics.informationGain.toFixed(3)}</span>
                            <span>PG {item.requested.metrics.performanceGain.toFixed(3)}</span>
                            <span>Risk {item.requested.metrics.risk.toFixed(3)}</span>
                            <span>Cost {item.requested.metrics.cost.toFixed(3)}</span>
                            <span>U(E) {item.requested.metrics.utility.toFixed(3)}</span>
                          </div>
                        </section>
                        <section className="approval-side-by-side__panel approval-side-by-side__panel--approved">
                          <span className="approval-compare-card__label">最终批准</span>
                          <strong>{item.approved?.candidateId || '--'}</strong>
                          <p>{item.approved?.summary ?? '当前尚未批准'}</p>
                          <div className="approval-compare-card__meta">
                            <span>U(E): {(item.approved?.utilityScore ?? 0).toFixed(3)}</span>
                          </div>
                          <div className="approval-metric-grid">
                            <span>IG {(item.approved?.metrics.informationGain ?? 0).toFixed(3)}</span>
                            <span>PG {(item.approved?.metrics.performanceGain ?? 0).toFixed(3)}</span>
                            <span>Risk {(item.approved?.metrics.risk ?? 0).toFixed(3)}</span>
                            <span>Cost {(item.approved?.metrics.cost ?? 0).toFixed(3)}</span>
                            <span>U(E) {(item.approved?.metrics.utility ?? 0).toFixed(3)}</span>
                          </div>
                          {item.approved?.notes ? <p className="approval-compare-card__notes">{item.approved.notes}</p> : null}
                        </section>
                      </div>
                      {item.review ? <p>{item.review.summary}</p> : null}
                      {item.notes ? <p className="approval-compare-card__notes">{item.notes}</p> : null}
                      <div className="approval-compare-card__section">
                        <span className="approval-compare-card__label">假设支持度变化</span>
                        <ul className="detail-list">
                          {item.hypothesisAssessments.slice(0, 4).map((assessment: any) => (
                            <li key={assessment.hypothesis_id}>
                              {assessment.hypothesis_id}：{formatDelta(assessment.support_before, assessment.support_after)}
                            </li>
                          ))}
                        </ul>
                      </div>
                      <div className="approval-compare-card__section">
                        <span className="approval-compare-card__label">不确定性收敛情况</span>
                        <ul className="detail-list">
                          {item.disagreementUpdates.slice(0, 3).map((update: any) => (
                            <li key={update.uncertainty_id}>
                              {update.uncertainty_id}：{formatDelta(update.support_span_before, update.support_span_after)}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </article>
                  ))}
                </div>
                {actionError ? <div className="timeline-empty-state timeline-empty-state--error">{actionError}</div> : null}
              </section>

              <div className="workspace-page__grid">
                <section className="detail-card">
                  <span className="detail-card__eyebrow">PI Decision</span>
                  <h2>人工审批动作</h2>
                  <div className="decision-option-row">
                    <button
                      type="button"
                      className="detail-link detail-link--button detail-link--accent"
                      onClick={() =>
                        queueApprovalAction('approve', {
                          candidateId: approvalOverlay?.recommendation.candidateId,
                          humanNotes: 'PI 采纳当前推荐实验并进入执行。',
                        })
                      }
                      disabled={actionBusy}
                    >
                      采纳推荐实验
                    </button>
                    <button
                      type="button"
                      className="detail-link detail-link--button"
                      onClick={() =>
                        queueApprovalAction('modify', {
                          candidateId: approvalOverlay?.recommendation.candidateId,
                          humanNotes: 'PI 要求在执行前调整参数与实验设置。',
                        })
                      }
                      disabled={actionBusy}
                    >
                      修改参数后采纳
                    </button>
                    <button
                      type="button"
                      className="detail-link detail-link--button"
                      onClick={() =>
                        queueApprovalAction('reject', {
                          candidateId: approvalOverlay?.recommendation.candidateId,
                          humanNotes: 'PI 拒绝当前推荐实验并要求重新选择。',
                        })
                      }
                      disabled={actionBusy}
                    >
                      拒绝并重选
                    </button>
                  </div>
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">Audit Trail</span>
                  <h2>审批记录</h2>
                  <div className="record-list">
                    {[...governance.approvals, ...governance.roundReviews].slice(0, 6).map((item: any) => (
                      <article key={item.decision_id} className="record-card">
                        <div className="record-card__header">
                          <strong>{item.decision_type}</strong>
                          <span>{item.timestamp ?? '--'}</span>
                        </div>
                        <p>{item.summary ?? '暂无摘要'}</p>
                      </article>
                    ))}
                  </div>
                </section>
              </div>
            </>
          )}
        </section>
        <StepConfirmDialog
          open={Boolean(pendingAction)}
          title={pendingAction?.title ?? '确认审批动作'}
          message={pendingAction?.message ?? '请确认当前审批动作。'}
          confirmLabel={pendingAction?.confirmLabel ?? '确认'}
          onCancel={() => setPendingAction(null)}
          onConfirm={() => {
            if (!pendingAction) {
              return
            }
            const nextAction = pendingAction
            setPendingAction(null)
            void submitAction(nextAction.action, nextAction.payload)
          }}
        />
      </div>
    </div>
  )
}
