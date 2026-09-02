import { useState } from 'react'
import { PageTabs } from '../components/PageTabs'
import { useTimelineBundle } from '../hooks/useTimelineBundle'

export function ExperimentEvaluationPage() {
  const { data, loading, error } = useTimelineBundle()
  const experiment = data?.viewModels.experimentEvaluation
  const [selectedVisualization, setSelectedVisualization] = useState<{
    label: string
    previewUrl: string
    path: string
  } | null>(null)

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取实验评价状态…</div>
          ) : error || !experiment ? (
            <div className="timeline-empty-state timeline-empty-state--error">
              {error ?? '实验评价数据不可用。'}
            </div>
          ) : (
            <>
              <header className="workspace-page__header">
                <div>
                  <span className="timeline-header__eyebrow">Experiment & Evaluation</span>
                  <h1>实验与评价</h1>
                  <p>候选实验、已执行实验、指标摘要和图表产物统一在此查看。</p>
                </div>

                <div className="detail-page__meta">
                  <div className="status-chip">
                    <span>推荐实验</span>
                    <strong>{experiment.recommendedExperimentId ?? '--'}</strong>
                  </div>
                  <div className="status-chip">
                    <span>已执行实验</span>
                    <strong>{experiment.experimentEntries.length}</strong>
                  </div>
                  <div className="status-chip">
                    <span>图表产物</span>
                    <strong>{experiment.visualizationPaths.length}</strong>
                  </div>
                </div>
              </header>

              <div className="workspace-page__grid">
                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Candidates</span>
                  <h2>候选实验矩阵</h2>
                  <div className="collection-grid">
                    {experiment.candidateExperiments.map((item: any, index: number) => (
                      <article key={item.experiment_id ?? index} className="collection-card">
                        <strong>{item.experiment_id ?? `candidate-${index + 1}`}</strong>
                        <p>{item.scientific_question ?? item.purpose ?? '暂无说明'}</p>
                        <div className="collection-card__meta">
                          <span>IG: {Number(item.estimated_information_gain?.value ?? item.estimated_information_gain ?? 0).toFixed(3)}</span>
                          <span>PG: {Number(item.estimated_performance_gain?.value ?? item.estimated_performance_gain ?? 0).toFixed(3)}</span>
                          <span>Risk: {Number(item.estimated_risk?.value ?? item.estimated_risk ?? 0).toFixed(3)}</span>
                          <span>Cost: {Number(item.estimated_cost?.value ?? item.estimated_cost ?? 0).toFixed(3)}</span>
                          <span>U(E): {Number(item.utility_score?.value ?? item.utility_score ?? 0).toFixed(3)}</span>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">Latest Evaluation</span>
                  <h2>最新评价</h2>
                  {experiment.latestEvaluation ? (
                    <div className="metrics-grid metrics-grid--two">
                      <div className="metric-box">
                        <span className="metric-box__label">Baseline r</span>
                        <span className="metric-box__value">{(experiment.latestEvaluation.baselinePearsonR ?? 0).toFixed(4)}</span>
                      </div>
                      <div className="metric-box">
                        <span className="metric-box__label">Treatment r</span>
                        <span className="metric-box__value">{(experiment.latestEvaluation.treatmentPearsonR ?? 0).toFixed(4)}</span>
                      </div>
                      <div className="metric-box metric-box--highlight">
                        <span className="metric-box__label">Delta r</span>
                        <span className="metric-box__value">{experiment.latestEvaluation.deltaPearsonR.toFixed(4)}</span>
                      </div>
                      <div className="metric-box">
                        <span className="metric-box__label">PG actual</span>
                        <span className="metric-box__value">{experiment.latestEvaluation.pgActual.toFixed(3)}</span>
                      </div>
                      <div className="metric-box">
                        <span className="metric-box__label">Delta RMSE</span>
                        <span className="metric-box__value">{(experiment.metricComparison?.deltaRmse ?? 0).toFixed(3)}</span>
                      </div>
                      <div className="metric-box">
                        <span className="metric-box__label">稳定性</span>
                        <span className="metric-box__value">{experiment.latestEvaluation.stable ? 'Stable' : 'Review'}</span>
                      </div>
                    </div>
                  ) : (
                    <div className="timeline-empty-state">暂无评价结果。</div>
                  )}
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">Metric Comparison</span>
                  <h2>Baseline / Treatment 对照</h2>
                  {experiment.metricComparison ? (
                    <div className="comparison-list">
                      <div className="comparison-row">
                        <span className="comparison-row__label">Pearson r</span>
                        <div className="comparison-row__bars">
                          <div className="comparison-bar comparison-bar--baseline">
                            <span>Baseline {(experiment.metricComparison.baselinePearsonR ?? 0).toFixed(4)}</span>
                          </div>
                          <div className="comparison-bar comparison-bar--treatment">
                            <span>Treatment {(experiment.metricComparison.treatmentPearsonR ?? 0).toFixed(4)}</span>
                          </div>
                        </div>
                      </div>
                      <div className="comparison-row">
                        <span className="comparison-row__label">RMSE</span>
                        <div className="comparison-row__bars">
                          <div className="comparison-bar comparison-bar--baseline">
                            <span>Baseline {(experiment.metricComparison.baselineRmse ?? 0).toFixed(3)}</span>
                          </div>
                          <div className="comparison-bar comparison-bar--treatment">
                            <span>Treatment {(experiment.metricComparison.treatmentRmse ?? 0).toFixed(3)}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="timeline-empty-state">暂无最新对照指标。</div>
                  )}
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">Executed</span>
                  <h2>已执行实验</h2>
                  <div className="record-list">
                    {experiment.experimentEntries.map((entry: any) => (
                      <article key={`${entry.round_id}-${entry.experiment_id}`} className="record-card">
                        <div className="record-card__header">
                          <strong>{entry.experiment_id}</strong>
                          <span>Round {entry.round_id ?? '--'}</span>
                        </div>
                        <p>{entry.key_findings?.[0] ?? '暂无关键发现'}</p>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Artifacts</span>
                  <h2>图表预览</h2>
                  <div className="visualization-grid">
                    {experiment.visualizationItems.map((item) => (
                      <article
                        key={item.path}
                        className="visualization-card visualization-card--interactive"
                        onClick={() =>
                          setSelectedVisualization({
                            label: item.label,
                            previewUrl: item.previewUrl,
                            path: item.path,
                          })
                        }
                      >
                        <div className="visualization-card__thumb visualization-card__thumb--image">
                          <img
                            src={item.previewUrl}
                            alt={item.label}
                            loading="lazy"
                          />
                          <span>{item.variant === 'baseline' ? 'Baseline' : item.variant === 'treatment' ? 'Treatment' : 'Artifact'}</span>
                        </div>
                        <strong>{item.label}</strong>
                        <p>{item.path}</p>
                      </article>
                    ))}
                  </div>
                </section>
              </div>
            </>
          )}
        </section>

        {selectedVisualization ? (
          <div
            className="preview-lightbox"
            role="dialog"
            aria-modal="true"
            onClick={() => setSelectedVisualization(null)}
          >
            <div className="preview-lightbox__panel" onClick={(event) => event.stopPropagation()}>
              <div className="preview-lightbox__header">
                <div>
                  <span className="detail-card__eyebrow">Visualization Preview</span>
                  <h2>{selectedVisualization.label}</h2>
                </div>
                <button
                  type="button"
                  className="detail-link detail-link--button"
                  onClick={() => setSelectedVisualization(null)}
                >
                  关闭
                </button>
              </div>
              <div className="preview-lightbox__image">
                <img src={selectedVisualization.previewUrl} alt={selectedVisualization.label} />
              </div>
              <p>{selectedVisualization.path}</p>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
