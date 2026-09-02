import type { TimelineNodeData } from '../types/timeline'

interface TimelineNodeProps {
  node: TimelineNodeData
  isSelected: boolean
  onSelect: (node: TimelineNodeData) => void
}

export function TimelineNode({ node, isSelected, onSelect }: TimelineNodeProps) {
  return (
    <button
      type="button"
      className={[
        'timeline-node',
        `timeline-node--${node.status}`,
        isSelected ? 'timeline-node--selected' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={() => onSelect(node)}
      title={node.title}
    >
      <span className="timeline-node__short">{node.shortLabel}</span>
      <span className="timeline-node__title">{node.title}</span>
    </button>
  )
}
