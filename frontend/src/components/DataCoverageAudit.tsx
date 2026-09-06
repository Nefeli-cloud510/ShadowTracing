import type { DataCoverageViewModel } from '../types/timeline'

function runLabel(runId?: string): string {
  if (runId === 'baseline') return '对照组'
  if (runId === 'treatment') return '实验组'
  return runId ?? '实验'
}

export function DataCoverageAudit({ items }: { items: DataCoverageViewModel[] }) {
  if (!items.length) {
    return (
      <section className="detail-card detail-card--wide">
        <span className="detail-card__eyebrow">Data Coverage Audit</span>
        <h2>数据覆盖与缺失日审计</h2>
        <p className="detail-card__meta">本轮未涉及稀疏数据源，无需额外的缺失日处理。</p>
      </section>
    )
  }

  return (
    <section className="detail-card detail-card--wide">
      <span className="detail-card__eyebrow">Data Coverage Audit</span>
      <h2>数据覆盖与缺失日审计</h2>
      <div className="coverage-grid">
        {items.map((item, index) => {
          const ratio =
            item.coverageRatio
            ?? (item.expectedDays ? (item.observedDays ?? 0) / item.expectedDays : 1)
          return (
            <article className="coverage-card" key={`${item.runId ?? 'run'}-${item.source ?? index}`}>
              <div className="coverage-card__head">
                <strong>{item.source ?? '数据源'} · {runLabel(item.runId)}</strong>
                <span className="coverage-card__ratio">{(ratio * 100).toFixed(1)}%</span>
              </div>
              <div className="coverage-card__meta">
                <span>有效覆盖 {item.observedDays ?? 0} / {item.expectedDays ?? 0} 天</span>
                <span>缺失 {item.missingDays ?? 0} 天</span>
                {typeof item.droppedGapWindows === 'number' && item.droppedGapWindows > 0 ? (
                  <span>已剔除跨缺失日窗口 {item.droppedGapWindows} 个</span>
                ) : null}
                {typeof item.interpolatedDays === 'number' && item.interpolatedDays > 0 ? (
                  <span>插值补全 {item.interpolatedDays} 天（已标记）</span>
                ) : null}
              </div>
              {item.note ? <p className="coverage-card__note">{item.note}</p> : null}
            </article>
          )
        })}
      </div>
    </section>
  )
}
