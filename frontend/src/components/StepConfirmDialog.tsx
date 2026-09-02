interface StepConfirmDialogProps {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  onConfirm: () => void
  onCancel: () => void
}

export function StepConfirmDialog({
  open,
  title,
  message,
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
          <p>{message}</p>
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
