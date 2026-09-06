import { useTimelineBundle } from '../hooks/useTimelineBundle'

export function WorkspaceRoundChip() {
  const { data } = useTimelineBundle()
  const currentRoundNumber = Number(
    data?.viewModels.currentRoundNumber ?? data?.snapshot.process?.current_round ?? 0,
  )

  if (!currentRoundNumber || currentRoundNumber <= 0) {
    return null
  }

  return (
    <div className="workspace-round-chip" title="当前闭环迭代轮次">
      <span>当前轮次</span>
      <strong>第 {currentRoundNumber} 轮</strong>
    </div>
  )
}
