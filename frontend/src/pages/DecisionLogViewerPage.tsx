import { useMemo, useState } from 'react'
import { PageTabs } from '../components/PageTabs'
import { useTimelineBundle } from '../hooks/useTimelineBundle'

export function DecisionLogViewerPage() {
  const { data, loading, error } = useTimelineBundle()
  const viewer = data?.viewModels.decisionLogViewer
  const [typeFilter, setTypeFilter] = useState('all')
  const [actorFilter, setActorFilter] = useState('all')
  const [search, setSearch] = useState('')

  const filteredRecords = useMemo(() => {
    if (!viewer) {
      return []
    }
    const query = search.trim().toLowerCase()
    return viewer.records.filter((item) => {
      const matchesType = typeFilter === 'all' || item.type === typeFilter
      const matchesActor = actorFilter === 'all' || item.actor === actorFilter
      const haystack = `${item.summary} ${item.details.join(' ')}`.toLowerCase()
      const matchesQuery = !query || haystack.includes(query)
      return matchesType && matchesActor && matchesQuery
    })
  }, [viewer, typeFilter, actorFilter, search])

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取决策日志…</div>
          ) : error || !viewer ? (
            <div className="timeline-empty-state timeline-empty-state--error">
              {error ?? '决策日志不可用。'}
            </div>
          ) : (
            <>
              <header className="workspace-page__header">
                <div>
                  <span className="timeline-header__eyebrow">Decision Log Viewer</span>
                  <h1>决策日志查看器</h1>
                  <p>按类型、执行者和关键词筛查系统决策、人工反馈与审计记录。</p>
                </div>
                <div className="detail-page__meta">
                  <div className="status-chip">
                    <span>总记录</span>
                    <strong>{viewer.records.length}</strong>
                  </div>
                  <div className="status-chip">
                    <span>类型数</span>
                    <strong>{viewer.availableTypes.length}</strong>
                  </div>
                  <div className="status-chip">
                    <span>执行者</span>
                    <strong>{viewer.availableActors.length}</strong>
                  </div>
                </div>
              </header>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Filters</span>
                <h2>筛选与搜索</h2>
                <div className="filter-toolbar">
                  <label className="filter-field">
                    <span>类型</span>
                    <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                      <option value="all">全部</option>
                      {viewer.availableTypes.map((item) => (
                        <option key={item} value={item}>
                          {item}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="filter-field">
                    <span>执行者</span>
                    <select value={actorFilter} onChange={(e) => setActorFilter(e.target.value)}>
                      <option value="all">全部</option>
                      {viewer.availableActors.map((item) => (
                        <option key={item} value={item}>
                          {item}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="filter-field filter-field--wide">
                    <span>关键词</span>
                    <input
                      type="text"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="搜索 summary / details"
                    />
                  </label>
                </div>
              </section>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Records</span>
                <h2>日志记录</h2>
                <div className="record-list">
                  {filteredRecords.map((record) => (
                    <article key={record.id} className="record-card">
                      <div className="record-card__header">
                        <strong>{record.summary}</strong>
                        <span>{record.timestamp ? new Date(record.timestamp).toLocaleString() : '--'}</span>
                      </div>
                      <div className="collection-card__meta">
                        <span>{record.type}</span>
                        <span>{record.actor}</span>
                        <span>Round {record.roundNumber ?? '--'}</span>
                      </div>
                      {record.details.length > 0 ? (
                        <ul className="detail-list">
                          {record.details.map((detail) => (
                            <li key={detail}>{detail}</li>
                          ))}
                        </ul>
                      ) : null}
                    </article>
                  ))}
                </div>
              </section>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
