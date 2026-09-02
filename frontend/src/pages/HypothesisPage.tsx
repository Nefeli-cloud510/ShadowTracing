import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { resetWorkflow } from '../api/liveWorkflow'
import { PageTabs } from '../components/PageTabs'
import { StepConfirmDialog } from '../components/StepConfirmDialog'
import { useTimelineBundle } from '../hooks/useTimelineBundle'
import { clearDataDictionaryDraft } from '../utils/dataDictionaryDraft'
import { clearMissionControllerDraft, clearUploadFiles, notifyWorkspaceReset } from '../utils/missionControllerPersistence'

export function HypothesisPage() {
  const navigate = useNavigate()
  const { data, loading, error, refresh } = useTimelineBundle()
  const [resetting, setResetting] = useState(false)
  const [confirmNextOpen, setConfirmNextOpen] = useState(false)
  const nodes = useMemo(() => {
    const rawNodes = data?.snapshot.hypothesisTree?.nodes ?? []
    return [...rawNodes]
      .sort((left: any, right: any) => {
        if ((left.level ?? 99) !== (right.level ?? 99)) {
          return (left.level ?? 99) - (right.level ?? 99)
        }
        return Number(right.support_score ?? 0) - Number(left.support_score ?? 0)
      })
  }, [data?.snapshot.hypothesisTree?.nodes])

  const groupedByLevel = useMemo(() => {
    return nodes.reduce<Record<number, any[]>>((accumulator, item: any) => {
      const level = Number(item.level ?? 1)
      accumulator[level] ??= []
      accumulator[level].push(item)
      return accumulator
    }, {})
  }, [nodes])

  const graphLayout = useMemo(() => {
    const levels = Object.keys(groupedByLevel)
      .map((item) => Number(item))
      .sort((left, right) => left - right)
    const width = Math.max(980, levels.length * 220 + 180)
    const positionMap = new Map<string, { x: number; y: number }>()

    levels.forEach((level, levelIndex) => {
      const levelNodes = groupedByLevel[level] ?? []
      const laneHeight = 130
      const totalHeight = Math.max(360, levelNodes.length * laneHeight)
      const baseOffset = Math.max(90, (520 - totalHeight) / 2 + 90)
      levelNodes.forEach((item, index) => {
        positionMap.set(item.hypothesis_id, {
          x: 140 + levelIndex * 220,
          y: baseOffset + index * laneHeight,
        })
      })
    })

    const edges = nodes
      .filter((item: any) => item.parent_id && positionMap.has(item.parent_id) && positionMap.has(item.hypothesis_id))
      .map((item: any) => {
        const from = positionMap.get(item.parent_id)!
        const to = positionMap.get(item.hypothesis_id)!
        return {
          id: `${item.parent_id}-${item.hypothesis_id}`,
          path: `M ${from.x} ${from.y} C ${from.x + 95} ${from.y}, ${to.x - 95} ${to.y}, ${to.x} ${to.y}`,
          status: item.status ?? 'observing',
        }
      })

    return {
      width,
      height: Math.max(560, ...Object.values(groupedByLevel).map((items) => items.length * 130 + 180)),
      levels,
      positions: positionMap,
      edges,
    }
  }, [groupedByLevel, nodes])

  const critiques = useMemo(
    () => {
      const traceCritiques = (data?.snapshot.plannerInput?.recent_reasoning_traces ?? [])
        .filter((item: any) => item.stage === 'scientific_questioner')
        .map((item: any, index: number) => ({
          hypothesisId: item.related_hypotheses?.[0] ?? `Q${index + 1}`,
          content: item.summary ?? '',
        }))
      if (traceCritiques.length > 0) {
        return traceCritiques.slice(0, 6)
      }
      return nodes
        .flatMap((item: any) =>
          (item.critiques ?? []).map((critique: any) => ({
            hypothesisId: item.hypothesis_id,
            content: critique.content,
          })),
        )
        .slice(0, 6)
    },
    [data?.snapshot.plannerInput?.recent_reasoning_traces, nodes],
  )

  const missionVariables = data?.viewModels.mission.variables

  function buildShortTitle(statement: string) {
    const x = missionVariables?.x || 'X'
    const y = missionVariables?.mCandidates?.[0] || missionVariables?.y || 'Y'
    const viaMatch = statement.match(/(.{1,16})(?:通过|via)(.{1,16})/i)
    if (viaMatch) {
      return `${viaMatch[1].trim()} via ${viaMatch[2].trim()}`
    }
    return `${x} via ${y}`
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
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取假设树…</div>
          ) : error ? (
            <div className="timeline-empty-state timeline-empty-state--error">{error}</div>
          ) : (
            <>
              <header className="workspace-page__header">
                <div>
                  <span className="timeline-header__eyebrow">Hypothesis Generation</span>
                  <h1>科学假设生成</h1>
                  <p>以知识图谱视角展示竞争假设的分叉、支持度与科学质询焦点，并保留一键清空假设空间记忆的能力。</p>
                </div>
                <div className="detail-links">
                  <button
                    type="button"
                    className="detail-link detail-link--button"
                    onClick={() => void handleClearMemory()}
                  >
                    {resetting ? '清空中…' : '清空假设空间记忆'}
                  </button>
                </div>
              </header>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Hypothesis Tree</span>
                <h2>假设空间状态数</h2>
                <div className="hypothesis-graph-panel">
                  <div className="hypothesis-graph-panel__legend">
                    <span>解释变量：{data?.viewModels.mission.variables.x || '待确认'}</span>
                    <span>目标变量：{data?.viewModels.mission.variables.y || data?.viewModels.mission.target || '待确认'}</span>
                    <span className="hypothesis-legend-item"><i className="hypothesis-legend-item__dot hypothesis-legend-item__dot--active" />活跃/支持</span>
                    <span className="hypothesis-legend-item"><i className="hypothesis-legend-item__dot hypothesis-legend-item__dot--observing" />观察中</span>
                    <span className="hypothesis-legend-item"><i className="hypothesis-legend-item__dot hypothesis-legend-item__dot--weakened" />削弱/剪枝</span>
                  </div>
                  <svg
                    className="hypothesis-graph"
                    viewBox={`0 0 ${graphLayout.width} ${graphLayout.height}`}
                    role="img"
                    aria-label="竞争假设图谱"
                  >
                    {graphLayout.edges.map((edge) => (
                      <path
                        key={edge.id}
                        d={edge.path}
                        className={`hypothesis-graph__edge hypothesis-graph__edge--${edge.status}`}
                        fill="none"
                      />
                    ))}
                    {nodes.map((item: any) => {
                      const position = graphLayout.positions.get(item.hypothesis_id)
                      if (!position) {
                        return null
                      }
                      return (
                        <g
                          key={item.hypothesis_id}
                          className="hypothesis-graph__node"
                          aria-label={item.statement}
                        >
                          <title>{item.statement}</title>
                          <circle
                            cx={position.x}
                            cy={position.y}
                            r={item.parent_id ? 16 : 20}
                            className={`hypothesis-graph__circle hypothesis-graph__circle--${item.status}`}
                            aria-label={item.statement}
                          />
                          <foreignObject x={position.x + 24} y={position.y - 34} width="180" height="86">
                            <div
                              className={`hypothesis-graph__callout hypothesis-graph__callout--${item.status}`}
                              title={item.statement}
                            >
                              <strong>{buildShortTitle(item.statement ?? item.hypothesis_id)}</strong>
                              <p>支持度 {Number(item.support_score ?? 0).toFixed(3)}</p>
                            </div>
                          </foreignObject>
                        </g>
                      )
                    })}
                  </svg>
                </div>
              </section>

              <div className="workspace-page__grid">
                <section className="detail-card">
                  <span className="detail-card__eyebrow">Questioning</span>
                  <h2>科学质询摘要</h2>
                  <div className="record-list">
                    {critiques.length > 0 ? (
                      critiques.map((item: { hypothesisId: string; content: string }) => (
                        <article key={`${item.hypothesisId}-${item.content}`} className="record-card">
                          <div className="record-card__header">
                            <strong>{item.hypothesisId}</strong>
                          </div>
                          <p>{item.content}</p>
                        </article>
                      ))
                    ) : (
                      <div className="timeline-empty-state">当前轮暂无科学质询摘要。</div>
                    )}
                  </div>
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">Next Step</span>
                  <h2>进入不确定性识别</h2>
                  <p>假设生成完成后，中央控制智能体会把关键分歧转成科学不确定性，供下一步候选实验规划使用。</p>
                  <div className="detail-links">
                    <button
                      type="button"
                      className="detail-link detail-link--button detail-link--accent"
                      onClick={() => setConfirmNextOpen(true)}
                    >
                      进入不确定性识别
                    </button>
                  </div>
                </section>
              </div>
            </>
          )}
        </section>
        <StepConfirmDialog
          open={confirmNextOpen}
          title="是否进入科学不确定性识别过程？"
          message="系统将根据当前假设树分歧和科学质询结果，进入不确定性优先级识别与候选实验驱动阶段。"
          confirmLabel="进入下一步"
          onCancel={() => setConfirmNextOpen(false)}
          onConfirm={() => navigate('/uncertainties')}
        />
      </div>
    </div>
  )
}
