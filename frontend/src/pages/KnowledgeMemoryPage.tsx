import { PageTabs } from '../components/PageTabs'
import { useTimelineBundle } from '../hooks/useTimelineBundle'

export function KnowledgeMemoryPage() {
  const { data, loading, error } = useTimelineBundle()
  const knowledge = data?.viewModels.knowledgeMemory
  const hypothesisTree = data?.snapshot.hypothesisTree
  const uncertainties = data?.snapshot.uncertainties

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取知识记忆状态…</div>
          ) : error || !knowledge ? (
            <div className="timeline-empty-state timeline-empty-state--error">
              {error ?? '知识记忆数据不可用。'}
            </div>
          ) : (
            <>
              <header className="workspace-page__header">
                <div>
                  <span className="timeline-header__eyebrow">Knowledge & Memory</span>
                  <h1>知识与记忆</h1>
                  <p>{knowledge.rootQuestion}</p>
                </div>

                <div className="detail-page__meta">
                  <div className="status-chip">
                    <span>总节点</span>
                    <strong>{knowledge.treeSummary.totalNodes}</strong>
                  </div>
                  <div className="status-chip">
                    <span>活跃假设</span>
                    <strong>{knowledge.treeSummary.activeCount}</strong>
                  </div>
                  <div className="status-chip">
                    <span>不确定性</span>
                    <strong>{knowledge.uncertaintyRecords.length}</strong>
                  </div>
                </div>
              </header>

              <div className="workspace-page__grid">
                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Highlighted Tree</span>
                  <h2>关键假设分支</h2>
                  <div className="collection-grid">
                    {knowledge.highlightedHypotheses.map((item) => (
                      <article key={item.id} className="collection-card">
                        <strong>{item.id}</strong>
                        <p>{item.label}</p>
                        <div className="collection-card__meta">
                          <span>状态: {item.status}</span>
                          <span>支持度: {item.supportScore.toFixed(3)}</span>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Full Tree History</span>
                  <h2>完整假设树历史</h2>
                  <div className="tree-history-list">
                    {(hypothesisTree?.nodes ?? []).map((item: any) => (
                      <article key={item.hypothesis_id} className="tree-history-card">
                        <div className="tree-history-card__header">
                          <strong>{item.hypothesis_id}</strong>
                          <span>{item.status ?? '--'}</span>
                        </div>
                        <p>{item.statement}</p>
                        <div className="support-history-strip">
                          {(item.support_history ?? []).map((history: any, index: number) => (
                            <div key={`${item.hypothesis_id}-${index}`} className="support-history-point">
                              <span className="support-history-point__round">R{history.round ?? '--'}</span>
                              <strong>{Number(history.score ?? 0).toFixed(3)}</strong>
                              <small>{history.event ?? '--'}</small>
                            </div>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">Queue</span>
                  <h2>不确定性优先队列</h2>
                  <div className="record-list">
                    {knowledge.uncertaintyQueue.map((item) => (
                      <article key={item.id} className="record-card">
                        <div className="record-card__header">
                          <strong>{item.id}</strong>
                          <span>{item.priorityScore.toFixed(2)}</span>
                        </div>
                        <p>{item.question}</p>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Uncertainty Timeline</span>
                  <h2>不确定性时间线</h2>
                  <div className="uncertainty-timeline">
                    {(uncertainties?.records ?? []).map((item: any) => (
                      <article key={item.uncertainty_id} className="uncertainty-timeline__card">
                        <div className="uncertainty-timeline__header">
                          <strong>{item.uncertainty_id}</strong>
                          <span>{item.resolution_status ?? item.status ?? '--'}</span>
                        </div>
                        <p>{item.question}</p>
                        <div className="uncertainty-timeline__events">
                          {(item.history ?? []).map((history: any, index: number) => (
                            <div key={`${item.uncertainty_id}-${index}`} className="uncertainty-event">
                              <span className="uncertainty-event__round">R{history.round ?? '--'}</span>
                              <div>
                                <strong>{history.event ?? '--'}</strong>
                                <p>{history.description ?? '--'}</p>
                              </div>
                            </div>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">RAG</span>
                  <h2>知识命中摘要</h2>
                  <div className="record-list">
                    {[...knowledge.ragSummaries.project, ...knowledge.ragSummaries.literature, ...knowledge.ragSummaries.external].map((item) => (
                      <article key={item} className="record-card">
                        <p>{item}</p>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Experiment Memory</span>
                  <h2>实验记忆</h2>
                  <div className="collection-grid">
                    {knowledge.experimentEntries.map((entry) => (
                      <article key={`${entry.round_id}-${entry.experiment_id}`} className="collection-card">
                        <strong>{entry.experiment_id}</strong>
                        <p>{entry.key_findings?.[0] ?? '暂无摘要'}</p>
                        <div className="collection-card__meta">
                          <span>Round {entry.round_id ?? '--'}</span>
                          <span>状态: {entry.status ?? '--'}</span>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
