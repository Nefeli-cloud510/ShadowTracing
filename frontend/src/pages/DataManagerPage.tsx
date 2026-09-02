import { PageTabs } from '../components/PageTabs'
import { useTimelineBundle } from '../hooks/useTimelineBundle'

function qualityStatusLabel(status: string) {
  return status === 'pass' ? '通过' : '待补充'
}

export function DataManagerPage() {
  const { data, loading, error } = useTimelineBundle()
  const manager = data?.viewModels.dataManager

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取数据管理状态…</div>
          ) : error || !manager ? (
            <div className="timeline-empty-state timeline-empty-state--error">
              {error ?? '数据管理状态不可用。'}
            </div>
          ) : (
            <>
              <header className="workspace-page__header">
                <div>
                  <span className="timeline-header__eyebrow">Data Manager</span>
                  <h1>数据管理页</h1>
                  <p>展示数据源映射、变量字典、资源预算与质量检查。</p>
                </div>
                <div className="detail-page__meta">
                  <div className="status-chip">
                    <span>数据源</span>
                    <strong>{manager.sources.length}</strong>
                  </div>
                  <div className="status-chip">
                    <span>变量字段</span>
                    <strong>{manager.variableDictionary.length}</strong>
                  </div>
                  <div className="status-chip">
                    <span>检查项</span>
                    <strong>{manager.qualityChecks.length}</strong>
                  </div>
                </div>
              </header>

              <div className="workspace-page__grid">
                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Sources</span>
                  <h2>数据源目录</h2>
                  <div className="collection-grid">
                    {manager.sources.map((item) => (
                      <article key={item.id} className="collection-card">
                        <strong>{item.id}</strong>
                        <p>{item.path ?? '--'}</p>
                        <div className="collection-card__meta">
                          <span>{item.role}</span>
                          <span>时间对齐字段：{item.timeColumn ?? '待识别'}</span>
                          <span>目标字段：{item.targetColumn ?? '待识别'}</span>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">Dictionary</span>
                  <h2>变量字典</h2>
                  <div className="record-list">
                    {manager.variableDictionary.map((item) => (
                      <article key={`${item.field}-${item.source}`} className="record-card">
                        <div className="record-card__header">
                          <strong>{item.field}</strong>
                          <span>{item.source}</span>
                        </div>
                        <p>{item.meaning}</p>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card">
                  <span className="detail-card__eyebrow">Budget</span>
                  <h2>资源预算</h2>
                  <div className="metrics-grid metrics-grid--two">
                    {manager.resourceBudget.map((item) => (
                      <div key={item.label} className="metric-box">
                        <span className="metric-box__label">{item.label}</span>
                        <span className="metric-box__value">{item.value}</span>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Quality Checks</span>
                  <h2>质量检查</h2>
                  <div className="collection-grid">
                    {manager.qualityChecks.map((item) => (
                      <article key={item.id} className="collection-card">
                        <strong>{item.label}</strong>
                        <p>{item.note}</p>
                        <div className="collection-card__meta">
                          <span>{qualityStatusLabel(item.status)}</span>
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
