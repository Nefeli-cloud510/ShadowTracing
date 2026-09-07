import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  confirmHypothesisTree,
  rerunScientificQuestioning,
  resetWorkflow,
  runScientificQuestioning,
  startWorkflow,
  startUncertaintyIdentification,
  undoScientificQuestioning,
  waitForLiveStage,
} from '../api/liveWorkflow'
import { PageTabs } from '../components/PageTabs'
import { StepConfirmDialog } from '../components/StepConfirmDialog'
import { useTimelineBundle } from '../hooks/useTimelineBundle'
import { toDisplayText } from '../data/realStateLoader'
import {
  loadUploadFiles,
  readMissionControllerDraft,
  resetHypothesisSpaceClientState,
} from '../utils/missionControllerPersistence'
import {
  deriveVariableSelections,
  readDataDictionaryDraft,
  serializeDraftForApi,
  validateDataDictionaryDraft,
} from '../utils/dataDictionaryDraft'

const CANONICAL_HYPOTHESIS_IDS = new Set([
  'H_shadow_incremental_gain',
  'H_by_mediated_path',
  'H_by_beyond_effect',
  'H_lead_time_window',
  'H_window_stability',
])
const isDisplayedHypothesis = (id: string) =>
  CANONICAL_HYPOTHESIS_IDS.has(id) || id.startsWith('H_supplemental_')

interface HypothesisEdit {
  statement?: string
  display_hypothesis_id?: string
  support_score?: number
  status?: string
  removed?: boolean
  human_suggestion?: string
}

export function HypothesisPage() {
  const navigate = useNavigate()
  const { data, loading, error, refreshing, refresh } = useTimelineBundle()
  const [resetting, setResetting] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [regenerateError, setRegenerateError] = useState<string | null>(null)
  const [confirmNextOpen, setConfirmNextOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [questioningOpen, setQuestioningOpen] = useState(false)
  const [questioning, setQuestioning] = useState(false)
  const [rerunQuestioning, setRerunQuestioning] = useState(false)
  const [undoingQuestioning, setUndoingQuestioning] = useState(false)
  const [questioningError, setQuestioningError] = useState<string | null>(null)
  const [uncertaintyStarting, setUncertaintyStarting] = useState(false)
  const [uncertaintyError, setUncertaintyError] = useState<string | null>(null)
  const [edits, setEdits] = useState<Record<string, Partial<HypothesisEdit>>>({})
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [reviewEditOpen, setReviewEditOpen] = useState(false)
  const [treeZoom, setTreeZoom] = useState(0.82)
  const [treePan, setTreePan] = useState({ x: 0, y: 0 })
  const [treePanning, setTreePanning] = useState(false)
  const treeViewportRef = useRef<HTMLDivElement | null>(null)
  const treeDragRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    panX: number
    panY: number
    moved: boolean
  } | null>(null)
  const dragMovedRef = useRef(false)
  const processStage = String(
    data?.snapshot.process?.current_stage ?? data?.snapshot.sessionStatus?.stage ?? '',
  )
  const sessionStatus = data?.snapshot.sessionStatus
  const nextRoundGenerating =
    sessionStatus != null &&
    sessionStatus.status === 'running' &&
    sessionStatus.stage !== 'scientific_questioning'
  const nextRoundGeneratingMessage =
    sessionStatus?.message
      ? `${sessionStatus.message} 生成大约需要5-15分钟，请耐心等待。`
      : '正在生成新的假设空间，请稍候刷新页面查看最新结果。生成大约需要5-15分钟，请耐心等待。'
  const questioningCompleted =
    data?.snapshot.hypothesisTree?.latest_update?.event === 'scientific_questioning_completed' ||
    processStage === 'awaiting_uncertainty_identification'
  const currentRoundNumber =
    Number(data?.viewModels.currentRoundNumber ?? data?.snapshot.process?.current_round ?? 0) || 0
  const rawNodes = useMemo(() => {
    const items = data?.snapshot.hypothesisTree?.nodes ?? []
    const uniqueById = new Map<string, any>()
    items.forEach((item: any) => {
      const id = String(item.hypothesis_id ?? '')
      if (
        id &&
        isDisplayedHypothesis(id) &&
        !uniqueById.has(id)
      ) {
        uniqueById.set(id, item)
      }
    })
    return [...uniqueById.values()]
  }, [data?.snapshot.hypothesisTree?.nodes])

  const hypothesisGeneratedAt = data?.snapshot.hypothesisTree?.generated_at
    ? new Date(String(data.snapshot.hypothesisTree.generated_at))
    : null
  const hypothesisSourceLabel = hypothesisGeneratedAt
    ? `LLM 生成于 ${hypothesisGeneratedAt.toLocaleString()}`
    : 'LLM 生成时间待记录'
  const removedIds = useMemo(() => {
    const removed = new Set<string>()
    const marked = Object.entries(edits)
      .filter(([, edit]) => edit.removed)
      .map(([id]) => id)
    const expandChildren = (parentId: string) => {
      rawNodes
        .filter((item: any) => String(item.parent_id ?? '') === parentId)
        .forEach((item: any) => {
          const childId = String(item.hypothesis_id ?? '')
          if (childId && !removed.has(childId)) {
            removed.add(childId)
            expandChildren(childId)
          }
        })
    }
    marked.forEach((id) => {
      if (id) {
        removed.add(id)
        expandChildren(id)
      }
    })
    return removed
  }, [edits, rawNodes])
  const nodes = useMemo(() => {
    const reviewedNodes = rawNodes
      .filter((item: any) => !removedIds.has(String(item.hypothesis_id ?? '')))
      .map((item: any) => ({
        ...item,
        ...(edits[String(item.hypothesis_id ?? '')] ?? {}),
      }))
    const officialNodes = reviewedNodes.filter((item: any) =>
      isDisplayedHypothesis(String(item.hypothesis_id ?? '')),
    )
    const deduped = [...officialNodes].filter((item: any, index: number, collection: any[]) => {
      const id = String(item.hypothesis_id ?? '')
      const signature = id || `${String(item.level ?? '')}|${String(item.parent_id ?? '')}|${String(item.statement ?? '').trim()}`
      return collection.findIndex((candidate: any) =>
        id
          ? String(candidate.hypothesis_id ?? '') === id
          : `${String(candidate.level ?? '')}|${String(candidate.parent_id ?? '')}|${String(candidate.statement ?? '').trim()}` === signature,
      ) === index
    })
    return deduped
      .sort((left: any, right: any) => {
        const labelRank = (item: any) => {
          const match = /^H(\d+)$/.exec(String(item.display_hypothesis_id ?? ''))
          return match ? Number(match[1]) : 99
        }
        if ((left.level ?? 99) !== (right.level ?? 99)) {
          return (left.level ?? 99) - (right.level ?? 99)
        }
        return labelRank(left) - labelRank(right)
      })
  }, [edits, rawNodes, removedIds])
  const selectedNode = nodes.find((item: any) => String(item.hypothesis_id ?? '') === selectedNodeId)
  const selectedNodeEdit = selectedNode
    ? (edits[String(selectedNode.hypothesis_id ?? '')] ?? {})
    : undefined
  const selectedQuestioning = selectedNode ? latestQuestioningRecord(selectedNode) : null

  const graphLayout = useMemo(() => {
    const STEP_X = 220
    const GAP_UNIT = 0.8
    const MARGIN_X = 150
    const ROOT_Y = 210
    const LEVEL_GAP = 300

    const byId = new Map<string, any>()
    const childrenByParent = new Map<string, any[]>()
    nodes.forEach((item: any) => {
      const id = String(item.hypothesis_id ?? '')
      byId.set(id, item)
    })
    nodes.forEach((item: any) => {
      const parentId = String(item.parent_id ?? '')
      if (!parentId || !byId.has(parentId)) {
        return
      }
      if (!childrenByParent.has(parentId)) {
        childrenByParent.set(parentId, [])
      }
      childrenByParent.get(parentId)!.push(item)
    })

    const leafCount = new Map<string, number>()
    function countLeaves(id: string): number {
      if (leafCount.has(id)) {
        return leafCount.get(id)!
      }
      const children = childrenByParent.get(id) ?? []
      if (children.length === 0) {
        leafCount.set(id, 1)
        return 1
      }
      const total = children.reduce((sum: number, child: any) => {
        return sum + countLeaves(String(child.hypothesis_id ?? ''))
      }, 0)
      leafCount.set(id, total)
      return total
    }

    const positionMap = new Map<string, { x: number; y: number }>()
    function placeSubtree(item: any, startUnits: number): number {
      const id = String(item.hypothesis_id ?? '')
      const children = childrenByParent.get(id) ?? []
      const level = Math.max(1, Number(item.level ?? 1))
      const y = ROOT_Y + (level - 1) * LEVEL_GAP
      if (children.length === 0) {
        positionMap.set(id, {
          x: MARGIN_X + (startUnits + 0.5) * STEP_X,
          y,
        })
        return 1
      }
      let cursor = startUnits
      let firstX: number | null = null
      let lastX = 0
      children.forEach((child: any) => {
        const widthUnits = placeSubtree(child, cursor)
        const childPosition = positionMap.get(String(child.hypothesis_id ?? ''))!
        if (firstX === null) {
          firstX = childPosition.x
        }
        lastX = childPosition.x
        cursor += widthUnits + GAP_UNIT
      })
      positionMap.set(id, {
        x: (firstX! + lastX) / 2,
        y,
      })
      return cursor - GAP_UNIT - startUnits
    }

    const rootNodes = nodes.filter((item: any) => {
      const parentId = String(item.parent_id ?? '')
      return !parentId || !byId.has(parentId)
    })
    rootNodes.forEach((item: any) => countLeaves(String(item.hypothesis_id ?? '')))
    let cursor = 0
    rootNodes.forEach((item: any) => {
      const widthUnits = placeSubtree(item, cursor)
      cursor += widthUnits + GAP_UNIT
    })

    const maxLevel = Math.max(1, ...nodes.map((item: any) => Number(item.level ?? 1)))
    const width = Math.max(880, MARGIN_X * 2 + Math.max(4, cursor - GAP_UNIT) * STEP_X)
    const height = ROOT_Y + (maxLevel - 1) * LEVEL_GAP + 190
    const root = { x: width / 2, y: ROOT_Y - 146 }

    const edges = nodes
      .filter(
        (item: any) =>
          item.parent_id &&
          positionMap.has(String(item.parent_id)) &&
          positionMap.has(String(item.hypothesis_id ?? '')),
      )
      .map((item: any) => {
        const from = positionMap.get(String(item.parent_id))!
        const to = positionMap.get(String(item.hypothesis_id))!
        const parentItem = byId.get(String(item.parent_id ?? ''))
        const parentRadius = parentItem?.parent_id ? 16 : 20
        const fromX = from.x
        const toX = to.x
        const fromBottomY = from.y + parentRadius
        const toTopY = to.y - 16
        const branchY = Math.max(
          fromBottomY + 60,
          Math.min(fromBottomY + 100, toTopY - 72),
        )
        const path =
          fromX === toX
            ? `M ${fromX} ${fromBottomY} L ${toX} ${toTopY}`
            : `M ${fromX} ${fromBottomY} L ${fromX} ${branchY} L ${toX} ${branchY} L ${toX} ${toTopY}`
        return {
          id: `${item.parent_id}-${item.hypothesis_id}`,
          path,
          status: item.status ?? 'observing',
        }
      })
    const rootBottomY = root.y + 54
    const childTopY = ROOT_Y - 20
    const rootLeft = root.x - 350
    const rootRight = root.x + 350
    const laneTop = rootBottomY + 8
    const laneBottom = ROOT_Y - 58
    const rootPositions = rootNodes.map((item: any) => ({
      item,
      toX: positionMap.get(String(item.hypothesis_id ?? ''))!.x,
    }))
    const leftChildren = rootPositions
      .filter((entry) => entry.toX < rootLeft)
      .sort((a, b) => b.toX - a.toX)
    const rightChildren = rootPositions
      .filter((entry) => entry.toX > rootRight)
      .sort((a, b) => a.toX - b.toX)
    const underChildren = rootPositions.filter(
      (entry) => entry.toX >= rootLeft && entry.toX <= rootRight,
    )
    const laneYs = (count: number) => {
      if (count === 0) {
        return []
      }
      if (count === 1) {
        return [Math.round((laneTop + laneBottom) / 2)]
      }
      const step = Math.max(3, (laneBottom - laneTop) / (count - 1))
      return Array.from({ length: count }, (_, index) =>
        Math.round(laneTop + index * step),
      )
    }
    const makeRootEdge = (entry: { item: any; toX: number }, startX: number, laneY: number) => {
      const horizontalOnly = startX === entry.toX
      const path = horizontalOnly
        ? `M ${startX} ${rootBottomY} L ${startX} ${childTopY}`
        : `M ${startX} ${rootBottomY} L ${startX} ${laneY} L ${entry.toX} ${laneY} L ${entry.toX} ${childTopY}`
      return {
        id: `root-${entry.item.hypothesis_id}`,
        path,
        status: 'active',
      }
    }
    const leftLanes = laneYs(leftChildren.length)
    const rightLanes = laneYs(rightChildren.length)
    // Near children take the lower lanes so longer side branches pass above them.
    const rootEdges = [
      ...leftChildren.map((entry, index) =>
        makeRootEdge(entry, rootLeft, leftLanes[leftLanes.length - 1 - index]),
      ),
      ...underChildren.map((entry) => makeRootEdge(entry, entry.toX, rootBottomY)),
      ...rightChildren.map((entry, index) =>
        makeRootEdge(entry, rootRight, rightLanes[rightLanes.length - 1 - index]),
      ),
    ]
    return {
      width,
      height,
      root,
      positions: positionMap,
      edges: [...rootEdges, ...edges],
      rootEdges,
    }
  }, [nodes])

  const fitTreeToViewport = () => {
    const viewport = treeViewportRef.current
    if (!viewport) {
      return
    }
    const rect = viewport.getBoundingClientRect()
    const contentWidth = graphLayout.width + 48
    const contentHeight = graphLayout.height + 92
    const scaleX = Math.max(0.22, (rect.width - 72) / contentWidth)
    const scaleY = Math.max(0.22, (rect.height - 120) / contentHeight)
    const scale = Number(Math.min(1.12, Math.min(scaleX, scaleY)).toFixed(2))
    setTreeZoom(scale)
    setTreePan({
      x: Math.max(24, (rect.width - graphLayout.width * scale) / 2),
      y: 24,
    })
  }

  useEffect(() => {
    fitTreeToViewport()
  }, [graphLayout.width, graphLayout.height, nodes.length])

  const handleTreePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null
    if (target?.closest?.('button, input, textarea, select, a')) {
      return
    }
    if (event.button !== 0) {
      return
    }
    treeDragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      panX: treePan.x,
      panY: treePan.y,
      moved: false,
    }
    dragMovedRef.current = false
    setTreePanning(true)
  }

  const handleTreePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = treeDragRef.current
    if (!drag || drag.pointerId !== event.pointerId) {
      return
    }
    const dx = event.clientX - drag.startX
    const dy = event.clientY - drag.startY
    if (!drag.moved && Math.hypot(dx, dy) < 5) {
      return
    }
    drag.moved = true
    dragMovedRef.current = true
    setTreePan({
      x: drag.panX + dx,
      y: drag.panY + dy,
    })
  }

  const handleTreePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (treeDragRef.current?.pointerId === event.pointerId) {
      treeDragRef.current = null
    }
    setTreePanning(false)
    if (dragMovedRef.current) {
      window.setTimeout(() => {
        dragMovedRef.current = false
      }, 120)
    }
  }

  const displayText = useMemo(
    () => (text?: string) => toDisplayText(text ?? '', data?.snapshot.plannerInput?.data_dictionary_summary),
    [data?.snapshot.plannerInput?.data_dictionary_summary],
  )

  function updateEdit(id: string, patch: Partial<HypothesisEdit>) {
    setEdits((previous) => ({
      ...previous,
      [id]: {
        ...(previous[id] ?? {}),
        ...patch,
      },
    }))
  }

  function toggleRemoved(id: string) {
    const removed = Boolean(edits[id]?.removed)
    updateEdit(id, { removed: !removed })
  }

  function buildConfirmNodes(): Array<Record<string, unknown>> {
    return rawNodes
      .filter((item: any) => !removedIds.has(String(item.hypothesis_id ?? '')))
      .map((item: any) => {
        const id = String(item.hypothesis_id ?? '')
        const edit = edits[id] ?? {}
        const childrenIds = Array.isArray(item.children_ids) ? item.children_ids : []
        return {
          ...item,
          statement: edit.statement ?? String(item.statement ?? ''),
          display_hypothesis_id: edit.display_hypothesis_id ?? item.display_hypothesis_id ?? null,
          support_score: Number(edit.support_score ?? item.support_score ?? 0),
          status: edit.status ?? String(item.status ?? 'draft'),
          children_ids: childrenIds.filter((childId: string) => !removedIds.has(String(childId))),
        }
      })
  }

  function hasTreeEdits() {
    return Object.values(edits).some((edit) => {
      return Boolean(
        edit.removed ||
        edit.statement?.trim() ||
        edit.display_hypothesis_id?.trim() ||
        edit.status ||
        edit.support_score !== undefined ||
        edit.human_suggestion?.trim(),
      )
    })
  }

  function buildShortTitle(statement: string) {
    const shown = toDisplayText(statement, data?.snapshot.plannerInput?.data_dictionary_summary)
    const trimmed = (shown ?? '').split(/[。；]/)[0]?.trim()
    if (!trimmed) {
      return '科学假设'
    }
    return trimmed.length > 26 ? `${trimmed.slice(0, 26)}…` : trimmed
  }

  function hypothesisLabel(item: any) {
    return item.display_hypothesis_id || (item.level ? `H${item.level}` : item.hypothesis_id ?? '科学假设')
  }

  function statusLabel(status?: string) {
    const labels: Record<string, string> = {
      converged: '可验证',
      active: '活跃',
      observing: '待观察',
      pending: '待定',
      draft: '草稿',
      pruned: '剪枝',
    }
    return labels[String(status ?? '')] || '待定/草稿'
  }

  function questioningDirectionLabel(direction?: string) {
    const labels: Record<string, string> = {
      supports: '支持',
      weakens: '削弱',
      clarifies: '澄清',
    }
    return labels[String(direction ?? '').toLowerCase()] || '未判定'
  }

  function questioningRecords(item: any) {
    const records = Array.isArray(item.questioning_records) ? item.questioning_records : []
    if (currentRoundNumber > 0) {
      return records.filter((record: any) => Number(record.round ?? 0) === currentRoundNumber)
    }
    return records
  }

  function latestQuestioningRecord(item: any) {
    const records = questioningRecords(item)
    return records.length > 0 ? records[records.length - 1] : null
  }

  function statusFromSupport(support: number): string {
    if (support >= 0.7) {
      return 'converged'
    }
    if (support >= 0.4) {
      return 'active'
    }
    if (support >= 0.2) {
      return 'observing'
    }
    return 'pruned'
  }

  function supportFromStatus(status: string, current: number): number | undefined {
    if (status === 'converged') {
      return Math.max(current, 0.7)
    }
    if (status === 'active') {
      return Math.min(0.69, Math.max(0.4, current))
    }
    if (status === 'observing') {
      return Math.min(0.39, Math.max(0.2, current))
    }
    if (status === 'pruned') {
      return Math.min(0.19, current)
    }
    return undefined
  }

  async function handleConfirmHypothesis() {
    if (confirming) {
      return
    }
    setConfirming(true)
    setConfirmError(null)
    setConfirmNextOpen(false)
    try {
      const payload: { humanNotes?: string; nodes?: Array<Record<string, unknown>> } = {}
      const suggestionParts = rawNodes
        .filter((item: any) => !removedIds.has(String(item.hypothesis_id ?? '')))
        .map((item: any) => {
          const id = String(item.hypothesis_id ?? '')
          const edit = edits[id] ?? {}
          const suggestion = String(edit.human_suggestion ?? '').trim()
          if (!suggestion) {
            return ''
          }
          return `${edit.display_hypothesis_id ?? item.display_hypothesis_id ?? id}：${suggestion}`
        })
        .filter(Boolean)
      if (suggestionParts.length > 0) {
        payload.humanNotes = suggestionParts.join('；')
      }
      if (hasTreeEdits()) {
        payload.nodes = buildConfirmNodes()
      }
      await confirmHypothesisTree(payload)
      await refresh()
      setQuestioningOpen(true)
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : '假设树确认失败，请稍后重试。')
      setConfirmNextOpen(true)
    } finally {
      setConfirming(false)
    }
  }

  async function handleStartScientificQuestioning() {
    if (questioning) {
      return
    }
    setQuestioning(true)
    setQuestioningError(null)
    setQuestioningOpen(false)
    try {
      const submitted = await runScientificQuestioning()
      if (submitted.status === 'running' || submitted.status === 'starting') {
        await waitForLiveStage({
          accept: (session) => session.status !== 'running' && session.status !== 'starting',
          reject: (session) => session.status === 'failed',
          timeoutMs: 600000,
          intervalMs: 5000,
        })
      }
      await refresh()
    } catch (err) {
      setQuestioningError(err instanceof Error ? err.message : '科学质询执行失败，请稍后重试。')
    } finally {
      setQuestioning(false)
    }
  }

  async function handleRerunScientificQuestioning() {
    if (questioning || rerunQuestioning) {
      return
    }
    setRerunQuestioning(true)
    setQuestioningError(null)
    try {
      const submitted = await rerunScientificQuestioning()
      if (submitted.status === 'running' || submitted.status === 'starting') {
        await waitForLiveStage({
          accept: (session) => session.status !== 'running' && session.status !== 'starting',
          reject: (session) => session.status === 'failed',
          timeoutMs: 600000,
          intervalMs: 5000,
        })
      }
      await refresh()
    } catch (err) {
      setQuestioningError(err instanceof Error ? err.message : '科学质询重新生成失败，请稍后重试。')
    } finally {
      setRerunQuestioning(false)
    }
  }

  async function handleUndoScientificQuestioning() {
    if (questioning || rerunQuestioning || undoingQuestioning) {
      return
    }
    setUndoingQuestioning(true)
    setQuestioningError(null)
    try {
      await undoScientificQuestioning()
      await refresh()
    } catch (err) {
      setQuestioningError(err instanceof Error ? err.message : '科学质询撤销失败，请稍后重试。')
    } finally {
      setUndoingQuestioning(false)
    }
  }

  async function handleEnterUncertainty() {
    if (uncertaintyStarting) {
      return
    }
    setUncertaintyStarting(true)
    setUncertaintyError(null)
    try {
      const submitted = await startUncertaintyIdentification()
      if (submitted.status === 'running' || submitted.status === 'starting') {
        await waitForLiveStage({
          accept: (session) => session.status !== 'running' && session.status !== 'starting',
          reject: (session) => session.status === 'failed',
          timeoutMs: 600000,
          intervalMs: 5000,
        })
      }
      await refresh()
      navigate('/uncertainties')
    } catch (err) {
      setUncertaintyError(err instanceof Error ? err.message : '进入不确定性识别失败，请稍后重试。')
    } finally {
      setUncertaintyStarting(false)
    }
  }

  const hasQuestioningOutput = nodes.some((item: any) => questioningRecords(item).length > 0)

  async function handleClearMemory() {
    try {
      setResetting(true)
      try {
        await resetWorkflow({ preserveUploadedFiles: true })
      } catch {
        // 假设空间清零应保留已上传数据；后端不可用时仍刷新前端状态。
      }
      await resetHypothesisSpaceClientState()
      setEdits({})
      setSelectedNodeId(null)
      setReviewEditOpen(false)
      await refresh()
    } finally {
      setResetting(false)
    }
  }

  async function handleRegenerateHypotheses() {
    if (regenerating || resetting || loading) {
      return
    }
    setRegenerating(true)
    setRegenerateError(null)
    setEdits({})
    setSelectedNodeId(null)
    setReviewEditOpen(false)
    try {
      const draft = readMissionControllerDraft()
      const [knowledgeFiles, dataFiles] = await Promise.all([
        loadUploadFiles('knowledge'),
        loadUploadFiles('data'),
      ])
      const dictionaryDraft = readDataDictionaryDraft()
      if (!draft?.question.trim()) {
        throw new Error('未找到科学问题，请回到智能体交互控制台重新配置后再生成假设。')
      }
      if (dataFiles.length === 0 && (draft.dataFiles ?? []).length === 0) {
        throw new Error('未找到已上传的实验数据，请回到智能体交互控制台上传文件后再生成假设。')
      }
      if ((draft.knowledgeFiles ?? []).length > 0 && knowledgeFiles.length === 0) {
        throw new Error('未找到已上传的知识材料，请回到智能体交互控制台上传文件后再生成假设。')
      }
      const dictionaryValidationError = validateDataDictionaryDraft(dictionaryDraft)
      if (dictionaryValidationError) {
        throw new Error(dictionaryValidationError)
      }
      const selections = deriveVariableSelections(dictionaryDraft)
      const xVariable =
        selections.xVariable || draft.confirmedX.trim() || draft.questionAnalysis?.x_variable?.trim() || ''
      const yVariable =
        selections.yVariable || draft.confirmedY.trim() || draft.questionAnalysis?.y_variable?.trim() || ''
      if (!xVariable || !yVariable) {
        throw new Error('解释变量或目标变量尚未确认，请回到数据变量库完成变量配置。')
      }
      const confirmedM = draft.confirmedM
        .split(/[，,、]/)
        .map((item) => item.trim())
        .filter(Boolean)
      const mCandidates =
        selections.mCandidates.length > 0
          ? selections.mCandidates
          : confirmedM.length > 0
            ? confirmedM
            : (draft.questionAnalysis?.m_candidates ?? [])
      await startWorkflow({
        question: draft.question.trim(),
        knowledgeFiles,
        dataFiles,
        rounds: 2,
        xVariable,
        yVariable,
        mCandidates,
        questionType: draft.questionType,
        dataDictionaryConfig: dictionaryDraft ? serializeDraftForApi(dictionaryDraft) : undefined,
      })
      await waitForLiveStage({
        accept: (session) => session.status !== 'running' && session.status !== 'starting',
        reject: (session) => session.status === 'failed',
        timeoutMs: 600000,
        intervalMs: 5000,
      })
      await refresh()
    } catch (err) {
      setRegenerateError(err instanceof Error ? err.message : '假设重新生成失败，请稍后重试。')
    } finally {
      setRegenerating(false)
    }
  }

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取假设树…</div>
          ) : error ? (
            <div className="timeline-empty-state timeline-empty-state--error">{error}</div>
          ) : (
            <>
              <header className="workspace-page__header">
                <div className="workspace-page__header-title">
                  <span className="timeline-header__eyebrow">Hypothesis Generation</span>
                  <h1>科学假设生成</h1>
                  <p>由LLM生成的科学假设空间，支持点击进行假设查阅、修改、及删除等操作，确认后可进行科学质询更新节点，之后进入下一步</p>
                </div>
                <div className="workspace-page__header-aside">
                  <div className="workspace-page__engine-panel">
                    <div className="workspace-page__engine-meta">
                      <div className="status-chip">
                        <span>当前轮次</span>
                        <strong>{currentRoundNumber > 0 ? `第 ${currentRoundNumber} 轮` : '待开始'}</strong>
                      </div>
                      <div className="status-chip">
                        <span>运行模型</span>
                        <strong>{String(data?.snapshot.sessionStatus?.model ?? 'qwen3.8-flash')}</strong>
                      </div>
                      <div className="status-chip">
                        <span>假设来源</span>
                        <strong>{hypothesisSourceLabel}</strong>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="detail-link detail-link--button workspace-page__refresh"
                      onClick={() => void refresh()}
                    >
                      {refreshing ? '刷新中…' : '刷新'}
                    </button>
                  </div>
                  <button
                    type="button"
                    className="detail-link detail-link--button workspace-page__clear"
                    onClick={() => void handleClearMemory()}
                  >
                    {resetting ? '清空中…' : '清空假设空间记忆'}
                  </button>
                </div>
              </header>

              {nextRoundGenerating ? (
                <div className="hypothesis-running-banner">
                  {nextRoundGeneratingMessage}
                </div>
              ) : null}

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Hypothesis Tree</span>
                <div className="detail-card__title-row">
                  <h2>假设空间状态树</h2>
                  {currentRoundNumber > 0 ? (
                    <span className="badge hypothesis-tree-status-tag">第 {currentRoundNumber} 轮</span>
                  ) : null}
                  {(data?.snapshot.process?.current_stage === 'awaiting_hypothesis_confirmation' ||
                    data?.snapshot.sessionStatus?.status === 'awaiting_hypothesis_confirmation') && (
                    <span className="badge hypothesis-tree-status-tag">待确认</span>
                  )}
                  {data?.snapshot.sessionStatus?.status === 'running' &&
                  data?.snapshot.sessionStatus?.stage === 'scientific_questioning' ? (
                    <span className="badge hypothesis-tree-status-tag">质询执行中</span>
                  ) : null}
                  {processStage === 'awaiting_scientific_questioning' &&
                  data?.snapshot.sessionStatus?.status !== 'running' ? (
                    <span className="badge hypothesis-tree-status-tag">质询待开始</span>
                  ) : null}
                  {questioningCompleted ? (
                    <span className="badge hypothesis-tree-status-tag">质询完成</span>
                  ) : null}
                </div>
                <div className="hypothesis-graph-panel">
                <div className="hypothesis-graph-panel__legend">
                  <span>解释变量：{displayText(data?.viewModels.mission.variables.x ?? '') || '待确认'}</span>
                  <span>目标变量：{displayText(data?.viewModels.mission.variables.y ?? data?.viewModels.mission.target ?? '') || '待确认'}</span>
                  <span className="hypothesis-legend-item"><i className="hypothesis-legend-item__dot hypothesis-legend-item__dot--converged" />可验证</span>
                  <span className="hypothesis-legend-item"><i className="hypothesis-legend-item__dot hypothesis-legend-item__dot--active" />活跃</span>
                  <span className="hypothesis-legend-item"><i className="hypothesis-legend-item__dot hypothesis-legend-item__dot--observing" />待观察</span>
                  <span className="hypothesis-legend-item"><i className="hypothesis-legend-item__dot hypothesis-legend-item__dot--pruned" />剪枝</span>
                  <span className="hypothesis-legend-item"><i className="hypothesis-legend-item__dot hypothesis-legend-item__dot--pending" />待定/草稿</span>
                </div>
                  {nodes.length === 0 ? (
                    <div className="hypothesis-graph-panel__empty">
                      <strong>假设空间已清空</strong>
                      <p>科学问题、数据变量库与上传文件仍然保留，可以直接重新生成假设。</p>
                      <button
                        type="button"
                        className="detail-link detail-link--button detail-link--accent"
                        onClick={() => void handleRegenerateHypotheses()}
                        disabled={regenerating || resetting || refreshing || loading}
                      >
                        {regenerating ? '重新生成中…' : '重新生成假设'}
                      </button>
                      {regenerating && !regenerateError ? (
                        <p className="timeline-empty-state">生成大约需要5-15分钟，请耐心等待。</p>
                      ) : null}
                      {regenerateError ? (
                        <p className="timeline-empty-state timeline-empty-state--error">{regenerateError}</p>
                      ) : null}
                    </div>
                  ) : (
                    <div
                      className={[
                        'hypothesis-tree-viewport',
                        treePanning ? 'hypothesis-tree-viewport--panning' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      ref={treeViewportRef}
                      onPointerDown={handleTreePointerDown}
                      onPointerMove={handleTreePointerMove}
                      onPointerUp={handleTreePointerUp}
                      onPointerCancel={handleTreePointerUp}
                    >
                      <div className="hypothesis-graph-controls" role="toolbar" aria-label="假设树画布控制">
                        <button
                          type="button"
                          className="hypothesis-graph-control"
                          title="放大"
                          aria-label="放大"
                          onClick={() =>
                            setTreeZoom((zoom) => Math.min(2, Number((zoom + 0.1).toFixed(2))))
                          }
                        >
                          ＋
                        </button>
                        <button
                          type="button"
                          className="hypothesis-graph-control"
                          title="缩小"
                          aria-label="缩小"
                          onClick={() =>
                            setTreeZoom((zoom) => Math.max(0.3, Number((zoom - 0.1).toFixed(2))))
                          }
                        >
                          －
                        </button>
                        <span className="hypothesis-graph-zoom-level">{Math.round(treeZoom * 100)}%</span>
                        <button
                          type="button"
                          className="hypothesis-graph-control"
                          title="适应画布"
                          aria-label="适应画布"
                          onClick={() => fitTreeToViewport()}
                        >
                          适应
                        </button>
                        <button
                          type="button"
                          className="hypothesis-graph-control"
                          title="重置视图"
                          aria-label="重置视图"
                          onClick={() => {
                            setTreeZoom(1)
                            setTreePan({ x: 0, y: 0 })
                          }}
                        >
                          重置
                        </button>
                      </div>
                      <svg
                        className="hypothesis-graph"
                        viewBox={`0 0 ${graphLayout.width} ${graphLayout.height}`}
                        width={graphLayout.width}
                        height={graphLayout.height}
                        role="img"
                        aria-label="竞争假设图谱"
                        style={{ transform: `translate(${treePan.x}px, ${treePan.y}px) scale(${treeZoom})` }}
                      >
                      {graphLayout.edges.map((edge) => (
                        <path
                          key={edge.id}
                          d={edge.path}
                          className={`hypothesis-graph__edge hypothesis-graph__edge--${edge.status ?? 'active'}`}
                          fill="none"
                        />
                      ))}
                      <foreignObject
                        x={graphLayout.root.x - 350}
                        y={graphLayout.root.y - 54}
                        width="700"
                        height="108"
                      >
                        <div className="hypothesis-graph__root">
                          <div>
                            <span className="hypothesis-graph__root-eyebrow">科学问题</span>
                            <strong>
                              {displayText(data?.snapshot.plannerInput?.scientific_question ?? '') || '当前科学问题'}
                            </strong>
                          </div>
                        </div>
                      </foreignObject>
                      {nodes.map((item: any) => {
                        const position = graphLayout.positions.get(item.hypothesis_id)
                        if (!position) {
                          return null
                        }
                        return (
                          <g
                            key={item.hypothesis_id}
                            className="hypothesis-graph__node"
                            aria-label={displayText(item.statement) || item.hypothesis_id}
                            role="button"
                            tabIndex={0}
                            onPointerUp={(event) => {
                              if (event.button !== 0 || dragMovedRef.current) {
                                return
                              }
                              setSelectedNodeId(String(item.hypothesis_id ?? ''))
                            }}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault()
                                setSelectedNodeId(String(item.hypothesis_id ?? ''))
                              }
                            }}
                          >
                            <title>{displayText(item.statement) || item.hypothesis_id}</title>
                            <circle
                              cx={position.x}
                              cy={position.y}
                              r={item.parent_id ? 16 : 20}
                              className={`hypothesis-graph__circle hypothesis-graph__circle--${item.status}`}
                              aria-label={displayText(item.statement) || item.hypothesis_id}
                            />
                            <foreignObject
                              x={position.x + (item.parent_id ? 16 : 20)}
                              y={position.y - 50}
                              width="180"
                              height="112"
                            >
                              <div
                                className={`hypothesis-graph__callout hypothesis-graph__callout--${item.status}`}
                                title={displayText(item.statement) || item.hypothesis_id}
                              >
                                <span className="hypothesis-graph__badge">{hypothesisLabel(item)}</span>
                                <strong>{buildShortTitle(item.statement ?? item.hypothesis_id)}</strong>
                                <p>支持度 {Number(item.support_score ?? 0).toFixed(3)}</p>
                              </div>
                            </foreignObject>
                          </g>
                        )
                      })}
                      </svg>
                    </div>
                  )}
                </div>
              </section>

              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Scientific Questioning</span>
                <div className="detail-card__title-row">
                  <h2>科学质询输出</h2>
                  <span className="badge hypothesis-tree-status-tag">LLM 逐条质询</span>
                  <button
                    type="button"
                    className="detail-link detail-link--button detail-link--panel-button hypothesis-questioning-rerun"
                    onClick={() => void handleRerunScientificQuestioning()}
                    disabled={questioning || rerunQuestioning || resetting}
                  >
                    {rerunQuestioning ? '重新生成中…' : '重新生成'}
                  </button>
                  <button
                    type="button"
                    className="detail-link detail-link--button detail-link--panel-button hypothesis-questioning-undo"
                    onClick={() => void handleUndoScientificQuestioning()}
                    disabled={questioning || rerunQuestioning || undoingQuestioning || resetting}
                    title="撤销本轮质询造成的支持度与状态变化，恢复到质询前快照"
                  >
                    {undoingQuestioning ? '撤销中…' : '撤销本轮质询'}
                  </button>
                </div>
                <div className="hypothesis-questioning-panel">
                  {hasQuestioningOutput ? (
                    nodes.map((item: any) => {
                      const record = latestQuestioningRecord(item)
                      if (!record) {
                        return null
                      }
                      return (
                        <article
                          key={`${String(item.hypothesis_id ?? '')}-${Number(record.round ?? 0)}`}
                          className="hypothesis-questioning-row"
                        >
                          <div className="hypothesis-questioning-row__summary">
                            <span className="hypothesis-graph__badge">{hypothesisLabel(item)}</span>
                            <span
                              className={`hypothesis-questioning-direction hypothesis-questioning-direction--${String(record.impact_direction ?? 'clarifies').toLowerCase()}`}
                            >
                              {questioningDirectionLabel(record.impact_direction)}
                            </span>
                            <strong>
                              {Number(record.support_before ?? 0).toFixed(3)} →{' '}
                              {Number(record.support_after ?? 0).toFixed(3)}
                            </strong>
                            <span
                              className={`hypothesis-status-badge hypothesis-status-badge--${String(record.status ?? 'pending')}`}
                            >
                              {statusLabel(record.status)}
                            </span>
                          </div>
                          <p className="hypothesis-questioning-row__rationale">
                            {displayText(String(record.rationale ?? ''))}
                          </p>
                          {record.falsification_basis ? (
                            <p className="hypothesis-questioning-row__basis">
                              <strong>可证否依据：</strong>
                              {displayText(String(record.falsification_basis))}
                            </p>
                          ) : null}
                          <p className="hypothesis-questioning-row__meta">
                            R{Number(record.round ?? 0)} · 强度 {Number(record.impact_strength ?? 0).toFixed(2)} · 置信{' '}
                            {Number(record.confidence ?? 0).toFixed(2)} ·{' '}
                            {record.source_type === 'experimental' || record.source_type === 'human'
                              ? '强证据'
                              : '顾问调整'}
                          </p>
                        </article>
                      )
                    })
                  ) : (
                    <div className="timeline-empty-state hypothesis-questioning-empty">
                      {currentRoundNumber > 0
                        ? `当前轮（第 ${currentRoundNumber} 轮）尚未产生科学质询输出；执行新的科学质询后，LLM 的逐假设结论会显示在这里。`
                        : '当前状态文件未留存逐假设质询结论；执行科学质询后，LLM 的逐假设结论会显示在这里。'}
                    </div>
                  )}
                </div>
              </section>

              <section className="detail-card">
                <span className="detail-card__eyebrow">Next Step</span>
                <h2>
                  {processStage === 'awaiting_human_approval'
                    ? '下一步：候选实验审批'
                    : questioningCompleted
                      ? '下一步：不确定性识别'
                      : '下一步：科学质询'}
                </h2>
                {processStage === 'awaiting_hypothesis_confirmation' ? (
                  <p>当前假设树处于待确认状态，确认后系统将由 LLM 逐条质询假设并更新支持度</p>
                ) : processStage === 'awaiting_scientific_questioning' ? (
                  <p>开始科学质询后，LLM 会更新各假设支持度与状态，你可以在这里直接看到变化。</p>
                ) : processStage === 'awaiting_uncertainty_identification' ? (
                  <p>科学质询已完成，假设树支持度与状态已更新，可以进入不确定性识别与候选实验规划。</p>
                ) : processStage === 'awaiting_human_approval' ? (
                  <p>科学质询已完成，候选实验已生成并等待审批。</p>
                ) : (
                  <p>假设生成完成后，中央控制智能体会先执行科学质询，再把关键分歧转成科学不确定性。</p>
                )}
                <div className="detail-links">
                  {processStage === 'awaiting_hypothesis_confirmation' ? (
                    <button
                      type="button"
                      className="detail-link detail-link--button detail-link--accent"
                      onClick={() => setConfirmNextOpen(true)}
                      disabled={confirming}
                    >
                      {confirming ? '确认中…' : '确认假设树'}
                    </button>
                  ) : null}
                  {processStage === 'awaiting_scientific_questioning' ? (
                    <button
                      type="button"
                      className="detail-link detail-link--button detail-link--accent"
                      onClick={() => setQuestioningOpen(true)}
                      disabled={questioning}
                    >
                      {questioning ? '质询执行中…' : '开始科学质询'}
                    </button>
                  ) : null}
                  {processStage === 'awaiting_uncertainty_identification' ? (
                    <button
                      type="button"
                      className="detail-link detail-link--button detail-link--accent"
                      onClick={() => void handleEnterUncertainty()}
                      disabled={uncertaintyStarting}
                    >
                      {uncertaintyStarting ? '正在进入…' : '进入不确定性识别'}
                    </button>
                  ) : null}
                </div>
                {confirmError ? <p className="timeline-empty-state timeline-empty-state--error">{confirmError}</p> : null}
                {questioningError ? <p className="timeline-empty-state timeline-empty-state--error">{questioningError}</p> : null}
                {uncertaintyError ? <p className="timeline-empty-state timeline-empty-state--error">{uncertaintyError}</p> : null}
              </section>
            </>
          )}
        </section>
        {!reviewEditOpen && selectedNode ? (
          <div
            className="approval-overlay"
            role="dialog"
            aria-modal="true"
            onClick={() => setSelectedNodeId(null)}
          >
            <div
              className="approval-overlay__panel approval-overlay__panel--compact hypothesis-node-panel"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="approval-overlay__header">
                <div>
                  <span className="detail-card__eyebrow">Hypothesis Inspector</span>
                  <h2>{hypothesisLabel(selectedNode)}</h2>
                </div>
                <span className={`hypothesis-status-badge hypothesis-status-badge--${selectedNode.status ?? 'pending'}`}>
                  {statusLabel(selectedNode.status)}
                </span>
              </div>
              <div className="hypothesis-node-detail">
                <div className="hypothesis-node-detail__row">
                  <span>假设陈述</span>
                  <p>{displayText(selectedNode.statement ?? '') || '（未填写陈述）'}</p>
                </div>
                <div className="hypothesis-node-detail__row">
                  <span>支持度</span>
                  <div className="hypothesis-node-detail__support">
                    <div className="hypothesis-node-detail__support-track">
                      <i
                        style={{
                          width: `${Math.min(100, Math.max(0, Number(selectedNode.support_score ?? 0) * 100))}%`,
                        }}
                      />
                    </div>
                    <strong>{Number(selectedNode.support_score ?? 0).toFixed(3)}</strong>
                  </div>
                </div>
                {selectedQuestioning ? (
                  <div className="hypothesis-node-detail__row">
                    <span>
                      最新质询 · R{Number(selectedQuestioning.round ?? 0)} ·{' '}
                      {questioningDirectionLabel(selectedQuestioning.impact_direction)}
                    </span>
                    <p>{displayText(String(selectedQuestioning.rationale ?? ''))}</p>
                    <p>
                      支持度 {Number(selectedQuestioning.support_before ?? 0).toFixed(3)} →{' '}
                      {Number(selectedQuestioning.support_after ?? 0).toFixed(3)}，状态：
                      {statusLabel(selectedQuestioning.status)}
                    </p>
                  </div>
                ) : null}
                {String(selectedNodeEdit?.human_suggestion ?? '').trim() ? (
                  <div className="hypothesis-node-detail__row">
                    <span>人工修改建议</span>
                    <p>{selectedNodeEdit?.human_suggestion}</p>
                  </div>
                ) : null}
              </div>
              <div className="approval-overlay__actions">
                <button
                  type="button"
                  className="detail-link detail-link--button detail-link--accent"
                  onClick={() => setReviewEditOpen(true)}
                >
                  编辑
                </button>
                <button
                  type="button"
                  className="detail-link detail-link--button"
                  onClick={() => setSelectedNodeId(null)}
                >
                  关闭
                </button>
              </div>
            </div>
          </div>
        ) : null}
        {reviewEditOpen ? (
          <div
            className="approval-overlay"
            role="dialog"
            aria-modal="true"
            onClick={() => {
              setReviewEditOpen(false)
              setSelectedNodeId(null)
            }}
          >
            <div
              className="approval-overlay__panel hypothesis-edit-panel"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="approval-overlay__header">
                <div>
                  <span className="detail-card__eyebrow">H/C Review</span>
                  <h2>假设树人工审阅与编辑</h2>
                </div>
              </div>
              <p className="hypothesis-edit-panel__intro">
                可在确认前修改假设编号与陈述、调整支持度、剪枝或删除节点，也可以保留当前竞争假设；确认后系统先由 LLM 科学质询并更新支持度，再基于这棵冻结树生成不确定性与候选实验。
              </p>
              <div className="hypothesis-review-panel">
                {(() => {
                  const target =
                    rawNodes.find((item: any) => String(item.hypothesis_id ?? '') === selectedNodeId) ??
                    (rawNodes.length > 0 ? rawNodes[0] : null)
                  if (!target) {
                    return <div className="timeline-empty-state">尚未生成可编辑的假设节点。</div>
                  }
                  const id = String(target.hypothesis_id ?? '')
                  const edit = edits[id] ?? {}
                  const removed = Boolean(edit.removed)
                  return (
                    <article key={id} className={`hypothesis-review-row${removed ? ' hypothesis-review-row--removed' : ''}`}>
                      <div className="hypothesis-review-row__meta">
                        <label className="hypothesis-review-row__label">
                          <span>编号</span>
                          <input
                            value={edit.display_hypothesis_id ?? target.display_hypothesis_id ?? ''}
                            onChange={(event) =>
                              updateEdit(id, { display_hypothesis_id: event.target.value })
                            }
                          />
                        </label>
                        <label className="hypothesis-review-row__label">
                          <span>支持度</span>
                          <input
                            type="number"
                            min={0}
                            max={1}
                            step={0.01}
                            value={Number(edit.support_score ?? target.support_score ?? 0)}
                            onChange={(event) => {
                              const nextScore = Number(event.target.value)
                              const currentStatus = edit.status ?? String(target.status ?? 'draft')
                              updateEdit(id, {
                                support_score: nextScore,
                                status: currentStatus === 'draft' ? 'draft' : statusFromSupport(nextScore),
                              })
                            }}
                          />
                        </label>
                        <label className="hypothesis-review-row__label">
                          <span>状态</span>
                          <select
                            value={edit.status ?? String(target.status ?? 'draft')}
                            onChange={(event) => {
                              const nextStatus = event.target.value
                              const currentScore = Number(edit.support_score ?? target.support_score ?? 0)
                              const nextScore = supportFromStatus(nextStatus, currentScore)
                              updateEdit(
                                id,
                                nextScore === undefined
                                  ? { status: nextStatus }
                                  : { status: nextStatus, support_score: nextScore },
                              )
                            }}
                          >
                            <option value="converged">可验证</option>
                            <option value="active">活跃</option>
                            <option value="observing">待观察</option>
                            <option value="pending">待定</option>
                            <option value="draft">草稿</option>
                            <option value="pruned">剪枝</option>
                          </select>
                        </label>
                      </div>
                      <label className="hypothesis-review-row__statement">
                        <span>假设陈述</span>
                        <textarea
                          rows={2}
                          value={edit.statement ?? String(target.statement ?? '')}
                          onChange={(event) => updateEdit(id, { statement: event.target.value })}
                        />
                      </label>
                      <div className="hypothesis-review-row__actions">
                        <button
                          type="button"
                          className="detail-link detail-link--button"
                          onClick={() => toggleRemoved(id)}
                        >
                          {removed ? '恢复该假设' : '删除该假设'}
                        </button>
                      </div>
                      <label className="hypothesis-review-row__suggestion">
                        <span>人工修改建议</span>
                        <textarea
                          rows={2}
                          value={edit.human_suggestion ?? ''}
                          placeholder="例如：保留当前竞争假设并上调支持度"
                          onChange={(event) =>
                            updateEdit(id, { human_suggestion: event.target.value })
                          }
                        />
                      </label>
                    </article>
                  )
                })()}
              </div>
              {Boolean(edits[String(selectedNodeId ?? '')]?.removed) ? (
                <p className="detail-card__meta">删除该假设时，其子节点也会一并剪除；仍可在确认前恢复。</p>
              ) : null}
              <div className="approval-overlay__actions hypothesis-edit-panel__actions">
                <button
                  type="button"
                  className="detail-link detail-link--button"
                  onClick={() => {
                    setReviewEditOpen(false)
                    setSelectedNodeId(null)
                  }}
                >
                  关闭
                </button>
                <span className="detail-links__spacer" />
                <button
                  type="button"
                  className="detail-link detail-link--button detail-link--accent"
                  onClick={() => setReviewEditOpen(false)}
                >
                  提交
                </button>
              </div>
            </div>
          </div>
        ) : null}
        <StepConfirmDialog
          open={confirmNextOpen}
          title="确认冻结假设树？"
          message="确认后系统将冻结当前假设树（含人工修改、剪枝与支持度调整），随后由 LLM 对每条假设展开科学质询并更新支持度。"
          confirmLabel={confirming ? '确认中…' : '确认'}
          onCancel={() => setConfirmNextOpen(false)}
          onConfirm={() => void handleConfirmHypothesis()}
        />
        <StepConfirmDialog
          open={questioningOpen}
          title="是否开始科学质询？"
          message="开始后 LLM 将逐条质询当前假设，更新支持度与状态；质询结果会直接回写到这张假设树上。"
          confirmLabel="开始科学质询"
          onCancel={() => setQuestioningOpen(false)}
          onConfirm={() => void handleStartScientificQuestioning()}
        />
      </div>
    </div>
  )
}
