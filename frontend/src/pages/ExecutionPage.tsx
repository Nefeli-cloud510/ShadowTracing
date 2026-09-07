import { useMemo } from 'react'
import { DataCoverageAudit } from '../components/DataCoverageAudit'
import { ModelTuningCard } from '../components/ModelTuningCard'
import { PageTabs } from '../components/PageTabs'
import { ThreeLayerConclusionView } from '../components/ThreeLayerConclusionView'
import { useTimelineBundle } from '../hooks/useTimelineBundle'
import type { ExperimentEvaluationViewModel } from '../types/timeline'

type VisualizationItem = NonNullable<ExperimentEvaluationViewModel['visualizationItems']>[number]

function VisualCard({
  item,
  title,
  experimentLabel,
  metric,
}: {
  item: VisualizationItem
  title: string
  experimentLabel: string
  metric?: string
}) {
  return (
    <article className="execution-visual-card">
      <div className="execution-visual-card__image">
        <img src={item.previewUrl} alt={item.label} loading="lazy" />
      </div>
      <div className="execution-visual-card__meta">
        <strong>{title}</strong>
        <span>实验 {experimentLabel} · {item.label}</span>
        {metric ? <span className="execution-visual-card__metric">{metric}</span> : null}
      </div>
    </article>
  )
}

function stepStatusLabel(status: string) {
  if (status === 'completed') return '已完成'
  if (status === 'running') return '进行中'
  if (status === 'failed') return '失败'
  if (status === 'skipped') return '已跳过'
  return '待执行'
}

function isExecutionActive(sessionStatus: { status?: string; stage?: string; message?: string } | null | undefined) {
  if (!sessionStatus || sessionStatus.status !== 'running') {
    return false
  }
  const stage = String(sessionStatus.stage ?? '')
  return (
    stage.includes('experiment_execution') ||
    stage.includes('result_analysis') ||
    stage.includes('evaluating') ||
    stage.includes('state_writeback')
  )
}

export function ExecutionPage() {
  const { data, loading, error, refresh, refreshing } = useTimelineBundle()
  const monitor = data?.viewModels.processMonitor
  const experiment = data?.viewModels.experimentEvaluation
  const report = data?.viewModels.roundReport
  const sessionStatus = data?.snapshot.sessionStatus
  const executionActive = isExecutionActive(sessionStatus)
  const currentRoundNumber = Number(
    data?.viewModels.currentRoundNumber ?? data?.snapshot.process?.current_round ?? 0,
  )
  const runningApproval = [...(data?.snapshot.decisionLog.decisions ?? [])]
    .reverse()
    .find(
      (item) =>
        item.decision_type === 'experiment_approved' &&
        (item.round_id ?? currentRoundNumber) === currentRoundNumber,
    )
  const runningExperimentId =
    typeof runningApproval?.details?.candidate_id === 'string'
      ? runningApproval.details.candidate_id
      : undefined

  const progressSteps = useMemo(() => {
    const executionStage = monitor?.stages.find((item) => item.id === 'experiment_execution')
    return executionStage?.steps ?? []
  }, [monitor?.stages])

  const visualCharts = useMemo(() => {
    const items = experiment?.visualizationItems ?? []
    const pickVariantItem = (
      variant: 'baseline' | 'treatment',
      matcher: (label: string) => boolean,
    ) => {
      const variantItems = items.filter((item) => item.variant === variant)
      return variantItems.find((item) => matcher(item.label.toLowerCase()))
    }
    const pickTimeseries = (variant: 'baseline' | 'treatment') =>
      pickVariantItem(variant, (label) => label.includes('timeseries'))
    const pickScatter = (variant: 'baseline' | 'treatment') =>
      pickVariantItem(variant, (label) => label.includes('scatter') && !label.includes('residual'))
    return {
      baselineTimeseries: pickTimeseries('baseline'),
      treatmentTimeseries: pickTimeseries('treatment'),
      baselineScatter: pickScatter('baseline'),
      treatmentScatter: pickScatter('treatment'),
    }
  }, [experiment?.visualizationItems])
  const executedExperimentId = experiment?.executedExperimentId ?? '--'

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
                    <span>推荐实验</span>
                    <strong>{experiment.recommendedExperimentId ?? monitor.currentStepDetail.recommendedExperimentId ?? '--'}</strong>
                  </div>
                  <div className="status-chip">
                    <span>已执行</span>
                    <strong>{experiment.executedExperimentId ?? (executionActive && runningExperimentId ? runningExperimentId : '--')}</strong>
                  </div>
                  <div className="status-chip">
                    <span>Round</span>
                    <strong>{monitor.currentRound}</strong>
                  </div>
                  <div className="status-chip">
                    <span>状态</span>
                    <strong>{executionActive ? '实验执行中' : monitor.currentStepDetail.status}</strong>
                  </div>
                </div>
              </header>

              {executionActive ? (
                <div className="execution-running-banner">
                  {sessionStatus?.message ?? '正在执行实验并生成结果，完成后本页会自动展示最新产物。'}
                </div>
              ) : null}

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
                <span className="detail-card__eyebrow">Execution Plan</span>
                <h2>最近已执行实验计划</h2>
                {experiment.executedExperimentId ? (
                  <p className="detail-card__meta">
                    实验编号 {experiment.executedExperimentId} · Round {experiment.evaluatedRound}
                  </p>
                ) : null}
                <div className="evaluation-summary-card">
                  <p>
                    {experiment.executionPlanSummary ?? '当前尚未生成可读的实验计划摘要，系统将继续沿用结构化协议执行。'}
                  </p>
                </div>
              </section>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Metrics</span>
                <h2>指标对照</h2>
                {experiment.metricComparison ? (
                  <div className="metrics-grid metrics-grid--two">
                    <div className="metric-box">
                      <span className="metric-box__label">对照组相关性</span>
                      <span className="metric-box__value">{(experiment.metricComparison.baselinePearsonR ?? 0).toFixed(4)}</span>
                    </div>
                    <div className="metric-box">
                      <span className="metric-box__label">实验组相关性</span>
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
                  <div className="timeline-empty-state">
                    {executionActive ? '实验执行中，正在生成评价指标。' : '暂无最新评价指标。'}
                  </div>
                )}
              </section>

              <ModelTuningCard
                modelParameters={experiment.modelParameters}
                tuningEntries={experiment.tuningEntries}
                tuningNarrative={experiment.tuningNarrative}
              />

              <DataCoverageAudit items={experiment.dataCoverage} />

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Key Visuals</span>
                <h2>实验图像</h2>
                <div className="execution-visual-comparison execution-visual-comparison--three-rows">
                  <div className="execution-visual-row execution-visual-row--timeseries">
                    <div className="execution-visual-row__header">
                      <strong>对照组实验 · {executedExperimentId} · 真实值 / 预测值对比图</strong>
                      <span>对照组 Pearson r {experiment.metricComparison?.baselinePearsonR?.toFixed(4) ?? '--'}</span>
                    </div>
                    {visualCharts.baselineTimeseries ? (
                      <VisualCard
                        key={visualCharts.baselineTimeseries.path}
                        item={visualCharts.baselineTimeseries}
                        title="真实值 / 预测值对比图"
                        experimentLabel={executedExperimentId}
                      />
                    ) : (
                      <div className="timeline-empty-state">
                        {executionActive ? '实验执行中，正在生成对照组图表。' : '对照组时间轴散点图尚未产出。'}
                      </div>
                    )}
                  </div>

                  <div className="execution-visual-row execution-visual-row--timeseries">
                    <div className="execution-visual-row__header">
                      <strong>实验组实验 · {executedExperimentId} · 真实值 / 预测值对比图</strong>
                      <span>实验组 Pearson r {experiment.metricComparison?.treatmentPearsonR?.toFixed(4) ?? '--'}</span>
                    </div>
                    {visualCharts.treatmentTimeseries ? (
                      <VisualCard
                        key={visualCharts.treatmentTimeseries.path}
                        item={visualCharts.treatmentTimeseries}
                        title="真实值 / 预测值对比图"
                        experimentLabel={executedExperimentId}
                      />
                    ) : (
                      <div className="timeline-empty-state">
                        {executionActive ? '实验执行中，正在生成实验组图表。' : '实验组时间轴散点图尚未产出。'}
                      </div>
                    )}
                  </div>

                  <div className="execution-visual-row execution-visual-row--scatter-pair">
                    <div className="execution-visual-row__header">
                      <strong>线性散点图</strong>
                      <span>左：对照组实验 · 右：实验组实验</span>
                    </div>
                    <div className="execution-visual-row__pair">
                      {visualCharts.baselineScatter ? (
                        <VisualCard
                          key={visualCharts.baselineScatter.path}
                          item={visualCharts.baselineScatter}
                          title="对照组实验 · 线性散点图"
                          experimentLabel={executedExperimentId}
                        />
                      ) : (
                        <div className="timeline-empty-state">
                          {executionActive ? '实验执行中，正在生成对照散点图。' : '对照组散点图尚未产出。'}
                        </div>
                      )}
                      {visualCharts.treatmentScatter ? (
                        <VisualCard
                          key={visualCharts.treatmentScatter.path}
                          item={visualCharts.treatmentScatter}
                          title="实验组实验 · 线性散点图"
                          experimentLabel={executedExperimentId}
                        />
                      ) : (
                        <div className="timeline-empty-state">
                          {executionActive ? '实验执行中，正在生成实验组散点图。' : '实验组散点图尚未产出。'}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </section>

              {report?.threeLayerConclusion && experiment.executedExperimentId ? (
                <ThreeLayerConclusionView conclusion={report.threeLayerConclusion} roundNumber={report.roundNumber} />
              ) : null}

              <div className="workspace-page__grid">
                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Scientific Evaluation</span>
                  <h2>评价产出摘要</h2>
                  {experiment.executedExperimentId ? (
                    <div className="evaluation-summary-card">
                      <ul className="detail-list">
                        {(report?.scientificConclusions ?? []).slice(0, 5).map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                      {report?.scientificConclusions?.length ? null : <p>当前轮尚未形成稳定评价结论。</p>}
                    </div>
                  ) : (
                    <div className="timeline-empty-state">
                      当前轮尚未执行实验；上一轮产物已归档至轮次快照。
                    </div>
                  )}
                </section>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
