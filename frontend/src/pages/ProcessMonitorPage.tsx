import { PageTabs } from '../components/PageTabs'
import { useTimelineBundle } from '../hooks/useTimelineBundle'

function stageStatusLabel(status: string) {
  if (status === 'completed') return '已完成'
  if (status === 'running') return '进行中'
  return '待执行'
}

export function ProcessMonitorPage() {
  const { data, loading, error } = useTimelineBundle()
  const monitor = data?.viewModels.processMonitor

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取实验进程监控状态…</div>
          ) : error || !monitor ? (
            <div className="timeline-empty-state timeline-empty-state--error">
              {error ?? '实验进程监控数据不可用。'}
            </div>
          ) : (
            <>
              <header className="workspace-page__header">
                <div>
                  <span className="timeline-header__eyebrow">Process Monitor</span>
                  <h1>实验进程监控仪表盘</h1>
                  <p>展示当前阶段、阶段列表、步骤详情与最近活动日志。</p>
                </div>

                <div className="detail-page__meta">
                  <div className="status-chip">
                    <span>Round</span>
                    <strong>{monitor.currentRound}</strong>
                  </div>
                  <div className="status-chip">
                    <span>当前阶段</span>
                    <strong>{monitor.currentPhase ?? '--'}</strong>
                  </div>
                  <div className="status-chip">
                    <span>推荐实验</span>
                    <strong>{monitor.currentStepDetail.recommendedExperimentId ?? '--'}</strong>
                  </div>
                </div>
              </header>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Current Phase</span>
                <h2>当前阶段与进度</h2>
                <div className="timeline-progress timeline-progress--embedded">
                  <div className="timeline-progress__label">
                    当前阶段: {monitor.currentPhase ?? '--'} | 进度: {monitor.progressPercentage}%
                  </div>
                  <div className="timeline-progress__bar">
                    <div className="timeline-progress__fill" style={{ width: `${monitor.progressPercentage}%` }} />
                  </div>
                </div>
              </section>

              <div className="workspace-page__grid">
                <section className="detail-card">
                  <span className="detail-card__eyebrow">Stages</span>
                  <h2>阶段列表</h2>
                  <div className="stage-list">
                    {monitor.stages.map((stage) => (
                      <article key={stage.id} className={`stage-card stage-card--${stage.status}`}>
                        <div className="stage-card__header">
                          <strong>{stage.label}</strong>
                          <span>{stageStatusLabel(stage.status)}</span>
                        </div>
                        {stage.timestamp ? <p>{new Date(stage.timestamp).toLocaleString()}</p> : null}
                        {stage.steps ? (
                          <div className="stage-card__steps">
                            {stage.steps.map((step) => (
                              <span key={step.id} className={`stage-step stage-step--${step.status}`}>
                                {step.label}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">Current Step</span>
                  <h2>当前步骤详情</h2>
                  <div className="record-card">
                    <div className="record-card__header">
                      <strong>{monitor.currentStepDetail.title}</strong>
                      <span>{monitor.currentStepDetail.status}</span>
                    </div>
                    <p>候选实验: {monitor.currentStepDetail.candidateCount}</p>
                    <p>推荐实验: {monitor.currentStepDetail.recommendedExperimentId ?? '--'}</p>
                    {monitor.pendingApprovalCandidateId ? <p>等待审批: {monitor.pendingApprovalCandidateId}</p> : null}
                  </div>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Recent Logs</span>
                  <h2>最近活动日志</h2>
                  <div className="record-list">
                    {monitor.recentLogs.map((log) => (
                      <article key={log.id} className="record-card">
                        <div className="record-card__header">
                          <strong>{log.summary}</strong>
                          <span>{log.timestamp ? new Date(log.timestamp).toLocaleString() : '--'}</span>
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
