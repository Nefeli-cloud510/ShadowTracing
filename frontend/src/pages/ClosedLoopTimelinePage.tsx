import { useEffect, useMemo, useState } from 'react'
import { PageTabs } from '../components/PageTabs'
import { useTimelineBundle } from '../hooks/useTimelineBundle'
import { useTabs } from '../contexts/TabContext'
import type {
  HypothesisPreviewNode,
  RoundData,
  TimelineNodeData,
} from '../types/timeline'
import { RoundSegment } from '../components/RoundSegment'

function getInitialSelection(round: RoundData) {
  const firstInteractiveNode =
    round.nodes.find((node) => node.status === 'active' || node.status === 'approval') ??
    round.nodes[0]

  return `${round.id}:${firstInteractiveNode.id}`
}

export function ClosedLoopTimelinePage() {
  const { data, loading, error } = useTimelineBundle()
  const activeRound = data?.round
  const { addTab } = useTabs()

  const [selectedNodeKey, setSelectedNodeKey] = useState('')
  const [isHypothesisDrawerOpen, setIsHypothesisDrawerOpen] = useState(false)
  const [timelineScale, setTimelineScale] = useState(1)

  useEffect(() => {
    if (activeRound && !selectedNodeKey) {
      setSelectedNodeKey(getInitialSelection(activeRound))
    }
  }, [activeRound, selectedNodeKey])

  const selectedNode = useMemo(() => {
    if (!activeRound) {
      return null
    }
    const [, nodeId] = selectedNodeKey.split(':')
    return (
      activeRound.nodes.find((node) => node.id === nodeId) ?? activeRound.nodes[0]
    )
  }, [activeRound, selectedNodeKey])

  function handleSelectNode(roundId: string, node: TimelineNodeData) {
    setSelectedNodeKey(`${roundId}:${node.id}`)
    addTab({
      id: `node-${roundId}-${node.id}`,
      title: `${node.shortLabel} 详情`,
      path: `/node/${roundId}/${node.id}`
    })
  }

  function renderHypothesisBadge(hypothesis: HypothesisPreviewNode) {
    return (
      <div
        key={hypothesis.id}
        className={`hypothesis-badge hypothesis-badge--${hypothesis.status}`}
      >
        <span className="hypothesis-badge__id">{hypothesis.id}</span>
        <span className="hypothesis-badge__label">{hypothesis.label}</span>
        <span className="hypothesis-badge__score">
          support {hypothesis.supportScore.toFixed(2)}
        </span>
      </div>
    )
  }

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <header className="timeline-header">
          <div className="timeline-header__brand">
            <span className="timeline-header__eyebrow">
              竞争假设驱动的实验规划与反馈系统
            </span>
            <h1>逐影ShadowTracing</h1>
            {activeRound?.questionSummary ? <p>{activeRound.questionSummary}</p> : null}
          </div>

          <div className="timeline-nav timeline-nav--tools">
            <div className="zoom-control" aria-label="Timeline zoom controls">
              <button
                type="button"
                className="timeline-nav__pill"
                onClick={() => setTimelineScale((value) => Math.max(0.8, value - 0.1))}
              >
                -
              </button>
              <span className="zoom-control__label">{Math.round(timelineScale * 100)}%</span>
              <button
                type="button"
                className="timeline-nav__pill"
                onClick={() => setTimelineScale((value) => Math.min(1.4, value + 0.1))}
              >
                +
              </button>
            </div>
            <button
              type="button"
              className="timeline-nav__pill timeline-nav__pill--accent"
              onClick={() => setIsHypothesisDrawerOpen(true)}
            >
              Hypothesis Tree
            </button>
          </div>
        </header>

        <section className="timeline-meta">
          <div className="timeline-meta__workspace">
            <div className="timeline-meta__icon" aria-hidden="true" />
            <div>
              <div className="timeline-meta__workspace-label">mission / active</div>
              <div className="timeline-meta__workspace-title">Round Workspace</div>
            </div>
          </div>

          <div className="timeline-meta__metrics">
            <div className="metric-pill">
              <span className="metric-pill__label">Current round</span>
              <span className="metric-pill__value">{activeRound?.title ?? '--'}</span>
            </div>
            <div className="metric-pill">
              <span className="metric-pill__label">State</span>
              <span className="metric-pill__value">{data?.processStage ?? '--'}</span>
            </div>
            <div className="metric-pill">
              <span className="metric-pill__label">Selected node</span>
              <span className="metric-pill__value">{selectedNode?.id ?? '--'}</span>
            </div>
            <div className="metric-pill">
              <span className="metric-pill__label">Mode</span>
              <span className="metric-pill__value">Work</span>
            </div>
          </div>
        </section>

        <main className="timeline-stage">
          <div className="timeline-scroll-area">
            {loading ? (
              <div className="timeline-empty-state">正在读取本地真实状态 JSON...</div>
            ) : error ? (
              <div className="timeline-empty-state timeline-empty-state--error">{error}</div>
            ) : activeRound ? (
              <div className="timeline-track">
                <RoundSegment
                  round={activeRound}
                  selectedNodeId={selectedNodeKey}
                  onSelectNode={(node) => handleSelectNode(activeRound.id, node)}
                  scale={timelineScale}
                />
              </div>
            ) : (
              <div className="timeline-empty-state">暂无可展示轮次。</div>
            )}
          </div>
        </main>

        <footer className="timeline-progress">
          <div className="timeline-progress__label">
            Round {data?.currentRoundNumber ?? '--'} · {data?.progressPercentage ?? 0}%
          </div>
          <div className="timeline-progress__bar">
            <div
              className="timeline-progress__fill"
              style={{ width: `${data?.progressPercentage ?? 0}%` }}
            />
          </div>
        </footer>

        <aside
          className={[
            'hypothesis-drawer',
            isHypothesisDrawerOpen ? 'hypothesis-drawer--open' : '',
          ]
            .filter(Boolean)
            .join(' ')}
          aria-hidden={!isHypothesisDrawerOpen}
        >
          <div className="hypothesis-drawer__header">
            <div>
              <span className="timeline-header__eyebrow">Hypothesis Tree</span>
              <h2>{activeRound?.title ?? 'Round'}</h2>
            </div>
            <button
              type="button"
              className="hypothesis-drawer__close"
              onClick={() => setIsHypothesisDrawerOpen(false)}
              aria-label="Close hypothesis drawer"
            >
              ×
            </button>
          </div>

          {activeRound && activeRound.hypotheses.length > 0 ? (
            <div className="hypothesis-tree-preview">
              {activeRound.hypotheses.map((hypothesis) => renderHypothesisBadge(hypothesis))}
            </div>
          ) : (
            <div className="hypothesis-drawer__empty">
              当前轮尚未生成假设树。进入假设生成步骤后，会自动在此抽屉展示分支。
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
