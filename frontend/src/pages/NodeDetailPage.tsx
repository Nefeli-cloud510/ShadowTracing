import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { PageTabs } from '../components/PageTabs'
import { useTimelineBundle } from '../hooks/useTimelineBundle'
import { useTabs } from '../contexts/TabContext'

function HypothesisTreeDetail({ rawTree }: { rawTree: any }) {
  if (!rawTree || !rawTree.nodes) return <p>暂无假设树数据。</p>
  return (
    <div className="tree-container">
      {Object.values(rawTree.nodes).map((n: any) => (
        <div key={n.id} className="tree-node" style={{ marginLeft: `${(n.id.match(/_/g)?.length || 0) * 20}px` }}>
          <div className={`tree-node__card tree-node__card--${n.status}`}>
            <strong>{n.id}</strong>: {n.label}
            <div className="tree-node__meta">
              <span>支持度: {Number(n.support_score || 0).toFixed(2)}</span>
              <span>状态: {n.status}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function CandidateExperimentDetail({ rawExperiments }: { rawExperiments: any }) {
  if (!rawExperiments || !rawExperiments.candidates) return <p>暂无候选实验数据。</p>
  return (
    <div className="matrix-container">
      {rawExperiments.candidates.map((e: any) => (
        <div key={e.id} className={`matrix-card ${e.is_recommended ? 'matrix-card--recommended' : ''}`}>
          <div className="matrix-card__header">
            <strong>{e.id}</strong>
            {e.is_recommended && <span className="badge">推荐</span>}
          </div>
          <p>目标假设: {e.target_hypothesis}</p>
          <div className="matrix-card__metrics">
            <span>IG: {Number(e.information_gain || 0).toFixed(2)}</span>
            <span>PG: {Number(e.performance_gain || 0).toFixed(2)}</span>
            <span>Cost: {Number(e.cost || 0).toFixed(2)}</span>
            <span>U(E): {Number(e.utility || 0).toFixed(2)}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function ApprovalDetail({ rawLog }: { rawLog: any }) {
  if (!rawLog || !rawLog.decisions) return <p>暂无审批记录。</p>
  const approvals = rawLog.decisions.filter((d: any) => d.type === 'human_approval' || d.type === 'pi_approval')
  return (
    <div className="approval-container">
      {approvals.map((a: any, idx: number) => (
        <div key={idx} className="approval-card">
          <div className="approval-card__header">
            <strong>{a.action}</strong>
            <span>{new Date(a.timestamp).toLocaleString()}</span>
          </div>
          <p>{a.reasoning}</p>
          {a.feedback && (
            <div className="approval-card__feedback">
              <strong>PI 反馈:</strong> {a.feedback}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export function NodeDetailPage() {
  const { roundId, nodeId } = useParams()
  const { data, loading, error } = useTimelineBundle()
  const { removeTab } = useTabs()

  const round = useMemo(() => {
    if (!data) return null
    return data.round.id === roundId ? data.round : data.round
  }, [data, roundId])

  const node = round?.nodes.find((item) => item.id === nodeId) ?? round?.nodes[0] ?? null

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="detail-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取本地真实状态 JSON...</div>
          ) : error ? (
            <div className="timeline-empty-state timeline-empty-state--error">{error}</div>
          ) : round && node ? (
            <>
              <header className="detail-page__header">
                <div>
                  <span className="timeline-header__eyebrow">节点详情页</span>
                  <h1>{node.title}</h1>
                  <p>{node.summary}</p>
                </div>

                <div className="detail-page__meta">
                  <div className="status-chip">
                    <span>Round</span>
                    <strong>{round.title}</strong>
                  </div>
                  <div className="status-chip">
                    <span>Node</span>
                    <strong>{node.id}</strong>
                  </div>
                  <div className="status-chip status-chip--outline">
                    <span>Status</span>
                    <strong>{node.status}</strong>
                  </div>
                </div>
              </header>

              <div className="detail-page__grid">
                {node.id === 'H' && (
                  <section className="detail-card detail-card--wide">
                    <span className="detail-card__eyebrow">Hypothesis Tree</span>
                    <h2>科学假设树</h2>
                    <HypothesisTreeDetail rawTree={round.rawHypothesisTree} />
                  </section>
                )}
                
                {node.id === 'E' && (
                  <section className="detail-card detail-card--wide">
                    <span className="detail-card__eyebrow">Candidate Matrix</span>
                    <h2>候选实验矩阵</h2>
                    <CandidateExperimentDetail rawExperiments={round.rawCandidateExperiments} />
                  </section>
                )}

                {node.id === 'P' && (
                  <section className="detail-card detail-card--wide">
                    <span className="detail-card__eyebrow">PI Approval</span>
                    <h2>人工审批记录</h2>
                    <ApprovalDetail rawLog={round.rawDecisionLog} />
                  </section>
                )}

                <section className="detail-card">
                  <span className="detail-card__eyebrow">结构化摘要</span>
                  <h2>当前节点作用</h2>
                  <p>{node.summary}</p>
                  <ul className="detail-list">
                    {(node.detailItems ?? []).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">状态来源</span>
                  <h2>后端映射</h2>
                  <ul className="detail-list">
                    <li>`task / process / decision_log`</li>
                    <li>`hypothesis_tree / uncertainties`</li>
                    <li>`experiment_memory / planner_input / planner_output`</li>
                  </ul>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">下一步入口</span>
                  <h2>相关操作</h2>
                  <div className="detail-links">
                    <button
                      type="button"
                      className="detail-link detail-link--button"
                      onClick={() => removeTab(`node-${roundId}-${nodeId}`)}
                    >
                      关闭当前页面
                    </button>
                  </div>
                </section>
              </div>
            </>
          ) : (
            <div className="timeline-empty-state">暂无详情数据。</div>
          )}
        </section>
      </div>
    </div>
  )
}
