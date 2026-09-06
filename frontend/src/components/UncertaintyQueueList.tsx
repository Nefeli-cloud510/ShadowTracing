type UncertaintyQueueListProps = {
  records: any[]
  displayText?: (text?: string) => string
  hypothesisLabel?: (id?: string) => string
  candidateLimit?: number
}

function statusLabel(status?: string): string {
  if (!status) {
    return '待确认'
  }
  const labels: Record<string, string> = {
    active: '活跃',
    resolved: '已解决',
    partially_resolved: '部分解决',
    deprecated: '已弃用',
    tracking: '持续跟踪',
    identified: '已识别',
    pending: '待执行',
  }
  return labels[status] ?? status.replace(/_/g, ' ')
}

export function UncertaintyQueueList({
  records,
  displayText = (text?: string) => text ?? '',
  hypothesisLabel,
  candidateLimit = 6,
}: UncertaintyQueueListProps) {
  if (records.length === 0) {
    return <p>当前没有可展示的不确定性记录。</p>
  }

  const defaultHypothesisLabel = (id?: string) => id ?? '--'
  const label = hypothesisLabel ?? defaultHypothesisLabel

  return (
    <div className="uncertainty-container">
      {records.map((item, index) => (
        <article key={item.uncertainty_id} className="uncertainty-card">
          <div className="uncertainty-card__header">
            <strong>不确定性 {index + 1}</strong>
            <span className="uncertainty-card__status">
              {statusLabel(item.resolution_status ?? item.status)}
            </span>
          </div>
          <p className="uncertainty-card__question">
            {displayText(item.question ?? item.description) || '未命名不确定性'}
          </p>
          <div className="uncertainty-card__meta">
            <span className="uncertainty-card__hypotheses">
              {(item.related_hypotheses ?? []).slice(0, 3).length > 0
                ? (item.related_hypotheses ?? []).slice(0, 3).map((hypothesisId: string, index: number) => (
                    <span key={`${item.uncertainty_id}-${hypothesisId}-${index}`} className="hypothesis-chip">
                      {label(hypothesisId)}
                    </span>
                  ))
                : '--'}
            </span>
            <span>
              区分实验：{item.resolving_experiment ?? `待生成（本轮候选上限 ${candidateLimit}）`}
            </span>
            {item.uncertainty_id ? <span>记录 ID：{item.uncertainty_id}</span> : null}
          </div>
          {(item.history ?? []).length > 0 ? (
            <div className="uncertainty-card__history">
              {(item.history ?? []).slice(0, 3).map((history: any, historyIndex: number) => (
                <div key={`${item.uncertainty_id}-${historyIndex}`} className="uncertainty-card__history-row">
                  <strong>R{history.round ?? '--'}</strong>
                  <span>{history.description ?? history.event ?? '--'}</span>
                </div>
              ))}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  )
}
