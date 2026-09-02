import type { RoundData } from '../types/timeline'

interface TimelineMiniMapProps {
  rounds: RoundData[]
  activeRoundId: string
  onSelectRound: (roundId: string) => void
}

export function TimelineMiniMap({
  rounds,
  activeRoundId,
  onSelectRound,
}: TimelineMiniMapProps) {
  return (
    <nav className="timeline-mini-map" aria-label="Round quick navigation">
      {rounds.map((round) => (
        <button
          key={round.id}
          type="button"
          className={[
            'timeline-mini-map__item',
            activeRoundId === round.id ? 'timeline-mini-map__item--active' : '',
          ]
            .filter(Boolean)
            .join(' ')}
          onClick={() => onSelectRound(round.id)}
        >
          <span className="timeline-mini-map__label">{round.title}</span>
          <span className="timeline-mini-map__sub">{round.stateLabel}</span>
        </button>
      ))}
    </nav>
  )
}
