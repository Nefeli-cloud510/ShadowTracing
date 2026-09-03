import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageTabs } from '../components/PageTabs'
import { StepConfirmDialog } from '../components/StepConfirmDialog'
import { useTimelineBundle } from '../hooks/useTimelineBundle'
import { filterSelectableCandidateExperiments } from '../utils/experimentValidation'

type FilterMode = 'all' | 'active' | 'resolved'

export function UncertaintyPage() {
  const navigate = useNavigate()
  const { data, loading, error } = useTimelineBundle()
  const [filterMode, setFilterMode] = useState<FilterMode>('all')
  const [confirmNextOpen, setConfirmNextOpen] = useState(false)
  const selectableCandidates = useMemo(
    () => filterSelectableCandidateExperiments(data?.snapshot.candidateExperiments?.candidates ?? []),
    [data?.snapshot.candidateExperiments?.candidates],
  )

  const queue = useMemo(() => {
    const prioritized = data?.snapshot.uncertainties?.priority_queue?.queue ?? []
    if (prioritized.length > 0) {
      return prioritized
    }

    const records = data?.snapshot.uncertainties?.records ?? []
    if (records.length > 0) {
      return [...records]
        .sort(
          (left: any, right: any) =>
            Number(right.priority_factors?.expected_information_gain ?? 0) -
            Number(left.priority_factors?.expected_information_gain ?? 0),
        )
        .map((item: any) => ({
          uncertainty_id: item.uncertainty_id,
          question: item.question,
          priority_score: Number(item.priority_factors?.expected_information_gain ?? 0),
          status: item.resolution_status ?? item.status ?? 'identified',
          estimated_resolution_round: item.created_at_round ?? undefined,
        }))
    }

    const candidateFallback = selectableCandidates
    return candidateFallback.slice(0, 5).map((candidate: any, index: number) => ({
      uncertainty_id: candidate.related_uncertainties?.[0] ?? `U_FALLBACK_${index + 1}`,
      question: candidate.scientific_question ?? candidate.purpose ?? '等待围绕当前分歧生成问题',
      priority_score: Number(candidate.estimated_information_gain?.value ?? 0.5),
      status: 'identified',
      estimated_resolution_round: data?.viewModels.currentRoundNumber ?? 1,
    }))
  }, [data?.snapshot.uncertainties, data?.viewModels.currentRoundNumber, selectableCandidates])

  const records = useMemo(() => {
    const raw = data?.snapshot.uncertainties?.records ?? []
    const baseRecords =
      raw.length > 0
        ? raw
        : queue.map((item: any) => ({
            uncertainty_id: item.uncertainty_id,
            question: item.question,
            related_hypotheses: [],
            priority_factors: {
              expected_information_gain: item.priority_score,
            },
            resolution_status: item.status,
            resolving_experiment: '待生成',
            history: [],
          }))
    return baseRecords.filter((item: any) => {
      if (filterMode === 'all') {
        return true
      }
      if (filterMode === 'active') {
        return !String(item.resolution_status ?? item.status ?? '').includes('resolved')
      }
      return String(item.resolution_status ?? item.status ?? '').includes('resolved')
    })
  }, [data?.snapshot.uncertainties?.records, filterMode, queue])

  const candidateLinks = useMemo(() => {
    return selectableCandidates.slice(0, 6).map((candidate: any) => ({
      id: candidate.experiment_id,
      question: candidate.scientific_question ?? candidate.purpose ?? '待补充实验目标',
      relatedUncertainties: candidate.related_uncertainties ?? [],
      insight: candidate.distinguishing_insight ?? '围绕当前关键分歧生成区分性实验。',
    }))
  }, [selectableCandidates])

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
                  <h1>科学不确定性队列</h1>
                  <p>在假设生成和科学质询之后，系统将核心分歧收敛为不确定性列表，并按优先级驱动候选实验生成。</p>
                </div>
              </header>

              <section className="detail-card detail-card--wide">
                <div className="uncertainty-filter-bar">
                  <strong>科学不确定性队列</strong>
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

                <div className="approval-metric-grid">
                  {queue.slice(0, 4).map((item: any) => (
                    <span key={item.uncertainty_id}>
                      {item.uncertainty_id} · 优先级 {Number(item.priority_score ?? 0).toFixed(3)}
                    </span>
                  ))}
                </div>

                <div className="uncertainty-column">
                  {records.map((item: any) => (
                    <article key={item.uncertainty_id} className="uncertainty-stack-card">
                      <div className="uncertainty-stack-card__header">
                        <div>
                          <strong>{item.uncertainty_id}</strong>
                          <span>优先级 {item.priority_factors?.expected_information_gain ?? '--'}</span>
                        </div>
                        <span>{item.resolution_status ?? item.status ?? '--'}</span>
                      </div>
                      <p>{item.question}</p>
                      <div className="uncertainty-stack-card__meta">
                        <span>涉及假设: {(item.related_hypotheses ?? []).slice(0, 3).join('，') || '--'}</span>
                        <span>区分实验: {item.resolving_experiment ?? '待生成'}</span>
                      </div>
                      <div className="uncertainty-stack-card__history">
                        {(item.history ?? []).slice(0, 3).map((history: any, index: number) => (
                          <div key={`${item.uncertainty_id}-${index}`} className="uncertainty-history-row">
                            <strong>R{history.round ?? '--'}</strong>
                            <span>{history.description ?? history.event ?? '--'}</span>
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </section>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Derivation Flow</span>
                <h2>不确定性驱动的候选实验生成过程</h2>
                <div className="approval-compare-grid">
                  {candidateLinks.length > 0 ? (
                    candidateLinks.map((item: { id: string; question: string; relatedUncertainties: string[]; insight: string }) => (
                      <article key={item.id} className="approval-compare-card">
                        <div className="approval-compare-card__header">
                          <strong>{item.id}</strong>
                          <span>{item.relatedUncertainties.join('，') || '待关联'}</span>
                        </div>
                        <p>{item.question}</p>
                        <div className="approval-compare-card__section">
                          <span className="approval-compare-card__label">上游不确定性</span>
                          <ul className="detail-list">
                            {(
                              item.relatedUncertainties.length > 0
                                ? item.relatedUncertainties
                                : ['首轮候选实验尚未从历史不确定性继承关联 ID，这是首次闭环生成时的正常现象。']
                            ).map((uncertaintyId: string) => (
                              <li key={`${item.id}-${uncertaintyId}`}>{uncertaintyId}</li>
                            ))}
                          </ul>
                        </div>
                        <div className="approval-compare-card__section">
                          <span className="approval-compare-card__label">区分性思路</span>
                          <p>{item.insight}</p>
                        </div>
                      </article>
                    ))
                  ) : (
                    <div className="timeline-empty-state">当前还未生成候选实验，请先完成科学问题解析和候选实验规划。</div>
                  )}
                </div>
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
