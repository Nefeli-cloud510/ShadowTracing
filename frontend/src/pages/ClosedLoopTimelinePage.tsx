import { useMemo, useState } from 'react'
import { resetWorkflow } from '../api/liveWorkflow'
import { PageTabs } from '../components/PageTabs'
import { useTimelineBundle } from '../hooks/useTimelineBundle'
import { useTabs } from '../contexts/TabContext'
import { clearDataDictionaryDraft } from '../utils/dataDictionaryDraft'
import { clearMissionControllerDraft, clearUploadFiles, notifyWorkspaceReset } from '../utils/missionControllerPersistence'

export function ClosedLoopTimelinePage() {
  const { data, loading, error, refreshing, refresh } = useTimelineBundle()
  const rounds = data?.viewModels.rounds ?? []
  const mission = data?.viewModels.mission
  const processMonitor = data?.viewModels.processMonitor
  const knowledgeBase = data?.viewModels.knowledgeBaseManager
  const sessionStatus = data?.snapshot.sessionStatus
  const { addTab } = useTabs()
  const [showHistoryRounds, setShowHistoryRounds] = useState(false)
  const [resetting, setResetting] = useState(false)
  const currentRound = useMemo(() => rounds.find((round) => round.isCurrent) ?? rounds[rounds.length - 1] ?? null, [rounds])
  const displayQuestion = mission?.scientificQuestion || currentRound?.questionSummary || ''
  const knowledgeCount = knowledgeBase?.collections.reduce((sum, item) => sum + item.count, 0) ?? 0
  const dataCount = mission?.dataSources.length ?? 0
  const dataTableNames = useMemo(
    () =>
      mission?.dataSources
        .map((item) => item.path?.replace(/\\/g, '/').split('/').pop() ?? item.id)
        .filter((item, index, array) => Boolean(item) && array.indexOf(item) === index) ?? [],
    [mission?.dataSources],
  )

  const displayedRounds = useMemo(() => {
    if (showHistoryRounds) {
      return rounds
    }
    return rounds.filter((round) => round.isCurrent).slice(-1)
  }, [rounds, showHistoryRounds])

  function handleOpenNode(roundId: string, nodeId: string, shortLabel: string) {
    addTab({
      id: `node-${roundId}-${nodeId}`,
      title: `${shortLabel} 详情`,
      path: `/node/${roundId}/${nodeId}`,
      roundId,
      nodeId,
    })
  }

  async function handleClearMemory() {
    try {
      setResetting(true)
      await resetWorkflow()
      clearDataDictionaryDraft()
      clearMissionControllerDraft()
      await clearUploadFiles()
      notifyWorkspaceReset()
      await refresh()
    } finally {
      setResetting(false)
    }
  }

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <header className="timeline-header">
          <div className="timeline-header__brand">
            <span className="timeline-header__eyebrow">ShadowTracing</span>
            <h1>逐影ShadowTracing</h1>
            <p>竞争假设驱动的实验规划与反馈系统</p>
          </div>

          <div className="timeline-nav timeline-nav--tools">
            <button
              type="button"
              className="timeline-nav__pill"
              onClick={() => setShowHistoryRounds((value) => !value)}
            >
              {showHistoryRounds ? '折叠历史轮' : `展开历史轮 (${Math.max(rounds.length - 1, 0)})`}
            </button>
            <button
              type="button"
              className="timeline-nav__pill"
              onClick={() => void handleClearMemory()}
            >
              {resetting ? '清空中' : '清空本轮闭环记忆'}
            </button>
            <button
              type="button"
              className="timeline-nav__pill"
              onClick={() => void refresh()}
            >
              {refreshing ? '刷新中' : '刷新状态'}
            </button>
          </div>
        </header>

        <section className="workflow-overview">
          <div className="workflow-overview__hero">
            <div className="workflow-overview__question-card workflow-overview__question-card--hero">
              <span className="detail-card__eyebrow">科学问题</span>
              <strong>{displayQuestion || '尚未录入科学问题'}</strong>
            </div>
          </div>

          <div className="timeline-meta__metrics workflow-overview__metrics">
            <div className="metric-pill">
              <span className="metric-pill__label">当前轮次</span>
              <span className="metric-pill__value">{data?.viewModels.currentRoundNumber ?? '--'}</span>
            </div>
            <div className="metric-pill">
              <span className="metric-pill__label">当前节点</span>
              <span className="metric-pill__value">{processMonitor?.currentStep ?? '--'}</span>
            </div>
            <div className="metric-pill">
              <span className="metric-pill__label">当前阶段</span>
              <span className="metric-pill__value">{processMonitor?.currentPhase ?? '--'}</span>
            </div>
            <div className="metric-pill">
              <span className="metric-pill__label">知识条目</span>
              <span className="metric-pill__value">{knowledgeCount || '--'}</span>
            </div>
            <div className="metric-pill">
              <span className="metric-pill__label">数据文件</span>
              <span className="metric-pill__value">{dataCount || '--'}</span>
            </div>
          </div>
        </section>

        <main className="workflow-board">
          {loading ? (
            <div className="timeline-empty-state">正在读取主流程状态…</div>
          ) : error ? (
            <div className="timeline-empty-state timeline-empty-state--error">{error}</div>
          ) : currentRound ? (
            <>
              <section className="workflow-board__main">
                <div className="workflow-step-rail">
                  {currentRound.nodes.map((node) => (
                    <button
                      key={node.id}
                      type="button"
                      className={`workflow-step workflow-step--${node.status}`}
                      onClick={() => handleOpenNode(currentRound.id, node.id, node.shortLabel)}
                    >
                      <span className="workflow-step__icon">{node.shortLabel}</span>
                      <span className="workflow-step__title">{node.title}</span>
                      <span className="workflow-step__summary">{node.summary}</span>
                    </button>
                  ))}
                </div>

                <div className="workflow-insight-grid">
                  <article className="detail-card">
                    <span className="detail-card__eyebrow">已上传文件</span>
                    <h2>知识与数据</h2>
                    <ul className="detail-list">
                      <li>知识材料: {knowledgeCount > 0 ? `已接入 ${knowledgeCount} 条知识线索` : '本轮尚未接入知识材料'}</li>
                      <li>
                        数据资源: {dataTableNames.join('，') || '暂无'}
                      </li>
                    </ul>
                  </article>

                  <article className="detail-card">
                    <span className="detail-card__eyebrow">当前焦点</span>
                    <h2>{currentRound.stateLabel}</h2>
                    <p>{currentRound.subtitle}</p>
                    {sessionStatus?.status === 'failed' ? (
                      <div className="failure-attribution-card">
                        <strong>失败归因</strong>
                        <p>{sessionStatus.message ?? '当前闭环运行失败，请检查实验协议、字段映射与数据约束。'}</p>
                        <p>
                          失败阶段：{processMonitor?.currentPhase ?? '--'} / {processMonitor?.currentStep ?? '--'}
                        </p>
                      </div>
                    ) : null}
                    <ul className="detail-list">
                      {currentRound.hypotheses.slice(0, 3).map((item) => (
                        <li key={item.id}>
                          {item.id} · {item.label} · {item.supportScore.toFixed(2)}
                        </li>
                      ))}
                    </ul>
                    <div className="detail-links">
                      <button
                        type="button"
                        className="detail-link detail-link--button"
                        onClick={() => void handleClearMemory()}
                      >
                        {resetting ? '正在清空假设空间…' : '清空假设空间记忆'}
                      </button>
                    </div>
                  </article>

                  <article className="detail-card">
                    <span className="detail-card__eyebrow">本轮结果</span>
                    <h2>评价摘要</h2>
                    {currentRound.evaluation ? (
                      <ul className="detail-list">
                        <li>实验: {currentRound.evaluation.experimentId ?? '--'}</li>
                        <li>Delta r: {currentRound.evaluation.deltaPearsonR.toFixed(4)}</li>
                        <li>PG actual: {currentRound.evaluation.pgActual.toFixed(3)}</li>
                        <li>结论: {currentRound.evaluation.verdict}</li>
                      </ul>
                    ) : (
                      <p>当前轮尚未完成执行评价。</p>
                    )}
                  </article>
                </div>
              </section>

              <section className="workflow-history">
                <div className="workflow-history__header">
                  <span className="detail-card__eyebrow">历史轮次</span>
                  <strong>轮次回看</strong>
                </div>
                <div className="workflow-history__list">
                  {displayedRounds.map((round) => (
                    <article key={round.id} className={`workflow-history-card ${round.isCurrent ? 'workflow-history-card--current' : ''}`}>
                      <div className="workflow-history-card__header">
                        <strong>Round {round.roundNumber}</strong>
                        <span>{round.stateLabel}</span>
                      </div>
                      <p>{round.questionSummary}</p>
                      <div className="workflow-history-card__meta">
                        <span>假设 {round.hypotheses.length}</span>
                        <span>不确定性 {round.uncertainties.length}</span>
                        <span>实验 {round.experiments.length}</span>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            </>
          ) : (
            <div className="timeline-empty-state">尚未开始实验，请先在中央控制智能体页输入科学问题并上传数据。</div>
          )}
        </main>

        <footer className="timeline-progress">
          <div className="timeline-progress__label">
            第 {data?.viewModels.currentRoundNumber ?? '--'} 轮 · {data?.viewModels.progressPercentage ?? 0}% · 最近刷新{' '}
            {data ? new Date(data.refreshedAt).toLocaleTimeString() : '--'}
          </div>
          <div className="timeline-progress__bar">
            <div className="timeline-progress__fill" style={{ width: `${data?.viewModels.progressPercentage ?? 0}%` }} />
          </div>
        </footer>
      </div>
    </div>
  )
}
