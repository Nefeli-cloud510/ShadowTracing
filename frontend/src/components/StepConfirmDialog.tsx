interface StepConfirmDialogProps {
  open: boolean
  title: string
  message: string
  sections?: Array<{ label: string; value: string }>
  footer?: string
  confirmLabel?: string
  cancelLabel?: string
  onConfirm: () => void
  onCancel: () => void
}

export function StepConfirmDialog({
  open,
  title,
  message,
  sections,
  footer,
  confirmLabel = '确认',
  cancelLabel = '取消',
  onConfirm,
  onCancel,
}: StepConfirmDialogProps) {
  if (!open) {
    return null
  }

  return (
    <div className="approval-overlay" role="dialog" aria-modal="true" onClick={onCancel}>
      <div className="approval-overlay__panel approval-overlay__panel--compact" onClick={(event) => event.stopPropagation()}>
        <div className="approval-overlay__header">
          <div>
            <span className="detail-card__eyebrow">Step Confirmation</span>
            <h2>{title}</h2>
          </div>
        </div>
        <div className="approval-overlay__summary">
          {sections && sections.length > 0 ? (
            <div className="step-confirm__sections">
              {sections.map((section) => (
                <div className="step-confirm__row" key={section.label}>
                  <span className="step-confirm__row-label">{section.label}</span>
                  <span className="step-confirm__row-value">{section.value}</span>
                </div>
              ))}
            </div>
          ) : (
            <p>{message}</p>
          )}
          {footer ? <p className="step-confirm__footer">{footer}</p> : null}
        </div>
        <div className="approval-overlay__actions">
          <button type="button" className="detail-link detail-link--button" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button type="button" className="detail-link detail-link--button detail-link--accent" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
