import { useMemo, useState } from 'react'
import { PageTabs } from '../components/PageTabs'
import { useTimelineBundle } from '../hooks/useTimelineBundle'

function stepStatusLabel(status: string) {
  if (status === 'completed') return '已完成'
  if (status === 'running') return '进行中'
  if (status === 'failed') return '失败'
  if (status === 'skipped') return '已跳过'
  return '待执行'
}

export function ExecutionPage() {
  const { data, loading, error, refresh, refreshing } = useTimelineBundle()
  const monitor = data?.viewModels.processMonitor
  const experiment = data?.viewModels.experimentEvaluation
  const report = data?.viewModels.roundReport
  const sessionStatus = data?.snapshot.sessionStatus
  const [selectedVisualization, setSelectedVisualization] = useState<{
    label: string
    previewUrl: string
    path: string
  } | null>(null)

  const progressSteps = useMemo(() => {
    const executionStage = monitor?.stages.find((item) => item.id === 'experiment_execution')
    return executionStage?.steps ?? []
  }, [monitor?.stages])

  const highlightedVisuals = useMemo(() => {
    return [...(experiment?.visualizationItems ?? [])].sort((left, right) => {
      const leftWeight =
        left.label.toLowerCase().includes('timeseries') || left.label.toLowerCase().includes('prediction')
          ? 2
          : left.label.toLowerCase().includes('scatter')
            ? 1
            : 0
      const rightWeight =
        right.label.toLowerCase().includes('timeseries') || right.label.toLowerCase().includes('prediction')
          ? 2
          : right.label.toLowerCase().includes('scatter')
            ? 1
            : 0
      return rightWeight - leftWeight
    })
  }, [experiment?.visualizationItems])

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取实验执行状态…</div>
          ) : error || !monitor || !experiment ? (
            <div className="timeline-empty-state timeline-empty-state--error">
              {error ?? '实验执行数据不可用。'}
            </div>
          ) : (
            <>
              <header className="workspace-page__header">
                <div>
                  <span className="timeline-header__eyebrow">Execution & Evaluation</span>
                  <h1>实验执行与结果评价</h1>
                  <p>突出展示真实值与预测值时序对照、线性散点关系，以及本轮分析评价结论。</p>
                </div>

                <div className="detail-page__meta">
                  <button
                    type="button"
                    className="detail-link detail-link--button"
                    onClick={() => void refresh()}
                  >
                    {refreshing ? '刷新中…' : '刷新'}
                  </button>
                  <div className="status-chip">
                    <span>实验</span>
                    <strong>{experiment.recommendedExperimentId ?? monitor.currentStepDetail.recommendedExperimentId ?? '--'}</strong>
                  </div>
                  <div className="status-chip">
                    <span>Round</span>
                    <strong>{monitor.currentRound}</strong>
                  </div>
                  <div className="status-chip">
                    <span>状态</span>
                    <strong>{monitor.currentStepDetail.status}</strong>
                  </div>
                </div>
              </header>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Execution Monitor</span>
                <h2>实验执行监控</h2>
                {sessionStatus?.status === 'failed' ? (
                  <div className="timeline-empty-state timeline-empty-state--error">
                    {sessionStatus.message ?? '当前实验执行已失败，请检查协议特征与数据列映射。'}
                  </div>
                ) : null}
                <div className="timeline-progress timeline-progress--embedded">
                  <div className="timeline-progress__label">进度: {monitor.progressPercentage}%</div>
                  <div className="timeline-progress__bar">
                    <div className="timeline-progress__fill" style={{ width: `${monitor.progressPercentage}%` }} />
                  </div>
                </div>
                <div className="execution-monitor-card">
                  <div className="execution-monitor-card__steps">
                    {progressSteps.length > 0 ? (
                      progressSteps.map((step) => (
                        <div key={step.id} className={`execution-step execution-step--${step.status}`}>
                          <span>{step.label}</span>
                          <strong>{stepStatusLabel(step.status)}</strong>
                        </div>
                      ))
                    ) : (
                      <div className="timeline-empty-state">当前没有执行步骤快照，已回退为阶段级显示。</div>
                    )}
                  </div>
                  <div className="execution-monitor-card__logs">
                    {monitor.recentLogs.slice(0, 6).map((log) => (
                      <div key={log.id} className="execution-log-row">
                        <strong>{log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : '--'}</strong>
                        <span>{log.summary}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Key Visuals</span>
                <h2>关键结果图</h2>
                <div className="evaluation-hero-grid">
                  {highlightedVisuals.length > 0 ? (
                    highlightedVisuals.slice(0, 4).map((item) => {
                      const lowerLabel = item.label.toLowerCase()
                      const visualTitle = lowerLabel.includes('timeseries') || lowerLabel.includes('prediction')
                        ? '真实值 / 预测值时序图'
                        : lowerLabel.includes('scatter')
                          ? '线性散点图'
                          : item.label

                      return (
                        <article
                          key={item.path}
                          className="evaluation-hero-card"
                          onClick={() =>
                            setSelectedVisualization({
                              label: item.label,
                              previewUrl: item.previewUrl,
                              path: item.path,
                            })
                          }
                        >
                          <div className="evaluation-hero-card__image">
                            <img src={item.previewUrl} alt={item.label} loading="lazy" />
                          </div>
                          <div className="evaluation-hero-card__meta">
                            <strong>{visualTitle}</strong>
                            <span>{item.label}</span>
                          </div>
                        </article>
                      )
                    })
                  ) : (
                    <div className="timeline-empty-state">当前轮尚未产出结果图。</div>
                  )}
                </div>
              </section>

              <div className="workspace-page__grid">
                <section className="detail-card">
                  <span className="detail-card__eyebrow">Metrics</span>
                  <h2>指标对照</h2>
                  {experiment.metricComparison ? (
                    <div className="metrics-grid metrics-grid--two">
                      <div className="metric-box">
                        <span className="metric-box__label">基线相关性</span>
                        <span className="metric-box__value">{(experiment.metricComparison.baselinePearsonR ?? 0).toFixed(4)}</span>
                      </div>
                      <div className="metric-box">
                        <span className="metric-box__label">实验后相关性</span>
                        <span className="metric-box__value">{(experiment.metricComparison.treatmentPearsonR ?? 0).toFixed(4)}</span>
                      </div>
                      <div className="metric-box metric-box--highlight">
                        <span className="metric-box__label">改善幅度</span>
                        <span className="metric-box__value">{(experiment.metricComparison.deltaPearsonR ?? 0).toFixed(4)}</span>
                      </div>
                      <div className="metric-box">
                        <span className="metric-box__label">误差变化</span>
                        <span className="metric-box__value">{(experiment.metricComparison.deltaRmse ?? 0).toFixed(3)}</span>
                      </div>
                    </div>
                  ) : (
                    <div className="timeline-empty-state">暂无最新评价指标。</div>
                  )}
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Scientific Evaluation</span>
                  <h2>评价产出摘要</h2>
                  <div className="evaluation-summary-card">
                    <ul className="detail-list">
                      {(report?.scientificConclusions ?? []).slice(0, 5).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                    {report?.scientificConclusions?.length ? null : <p>当前轮尚未形成稳定评价结论。</p>}
                  </div>
                </section>
              </div>
            </>
          )}
        </section>

        {selectedVisualization ? (
          <div className="preview-lightbox" role="dialog" aria-modal="true" onClick={() => setSelectedVisualization(null)}>
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
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
