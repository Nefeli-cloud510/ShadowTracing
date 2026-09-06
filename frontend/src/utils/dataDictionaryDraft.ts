import type { DataInspectionResult } from '../api/liveWorkflow'
import { readWorkspaceResetAt } from './missionControllerPersistence'

export type VariableCategory = 'core_explanatory' | 'target' | 'candidate_mediator' | 'deprecated'

export interface DataDictionaryFieldDraft {
  fieldName: string
  fileName: string
  dataType: string
  isNumeric: boolean
  missingRate: number
  category: VariableCategory
  physicalMeaning: string
  displayName: string
}

export interface DataDictionaryDraft {
  timeColumn?: string
  fields: DataDictionaryFieldDraft[]
  sourceFiles: string[]
  updatedAt: string
  confirmedAt?: string
}

const STORAGE_KEY = 'shadowtracing.dataDictionaryDraft'

export function buildDataDictionaryDraft(inspection: DataInspectionResult): DataDictionaryDraft {
  return {
    timeColumn: inspection.suggested.time_column,
    sourceFiles: inspection.tables.map((table) => table.file_name),
    updatedAt: new Date().toISOString(),
    fields: inspection.tables.flatMap((table) =>
      table.columns.map((column) => ({
        fieldName: column.field_name,
        fileName: table.file_name,
        dataType: column.data_type,
        isNumeric: column.is_numeric,
        missingRate: column.missing_rate,
        category: normalizeCategory(column.suggested_category),
        physicalMeaning: column.physical_meaning ?? '',
        displayName: column.display_name ?? column.physical_meaning ?? '',
      })),
    ),
  }
}

export function mergeDataDictionaryDraft(
  inspection: DataInspectionResult,
  previousDraft: DataDictionaryDraft | null,
): DataDictionaryDraft {
  const previousFieldMap = new Map(
    (previousDraft?.fields ?? []).map((field) => [`${field.fileName}::${field.fieldName}`, field] as const),
  )

  return {
    timeColumn: inspection.suggested.time_column ?? previousDraft?.timeColumn,
    sourceFiles: inspection.tables.map((table) => table.file_name),
    updatedAt: new Date().toISOString(),
    confirmedAt: previousDraft && sourceFileListMatches(previousDraft.sourceFiles, inspection.tables.map((table) => table.file_name))
      ? previousDraft.confirmedAt
      : undefined,
    fields: inspection.tables.flatMap((table) =>
      table.columns.map((column) => {
        const previous = previousFieldMap.get(`${table.file_name}::${column.field_name}`)
        return {
          fieldName: column.field_name,
          fileName: table.file_name,
          dataType: column.data_type,
          isNumeric: column.is_numeric,
          missingRate: column.missing_rate,
          category: previous?.category ?? normalizeCategory(column.suggested_category),
          physicalMeaning: previous?.physicalMeaning ?? column.physical_meaning ?? '',
          displayName: previous?.displayName ?? column.display_name ?? column.physical_meaning ?? '',
        }
      }),
    ),
  }
}

export function readDataDictionaryDraft(): DataDictionaryDraft | null {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return null
    }
    const draft = JSON.parse(raw) as DataDictionaryDraft
    const resetAt = readWorkspaceResetAt()
    if (!resetAt) {
      return draft
    }
    return draft.updatedAt > resetAt ? draft : null
  } catch {
    return null
  }
}

export function writeDataDictionaryDraft(draft: DataDictionaryDraft) {
  if (typeof window === 'undefined') {
    return
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(draft))
}

export function clearDataDictionaryDraft() {
  if (typeof window === 'undefined') {
    return
  }
  window.localStorage.removeItem(STORAGE_KEY)
}

export function serializeDraftForApi(draft: DataDictionaryDraft) {
  return {
    time_column: draft.timeColumn,
    fields: draft.fields.map((field) => ({
      field_name: field.fieldName,
      file_name: field.fileName,
      category: field.category,
      physical_meaning: field.physicalMeaning.trim(),
      display_name: field.displayName.trim() || field.physicalMeaning.trim(),
    })),
  }
}

export function deriveVariableSelections(draft: DataDictionaryDraft | null) {
  if (!draft) {
    return {
      xVariable: '',
      yVariable: '',
      mCandidates: [] as string[],
      displayX: '',
      displayY: '',
      displayMCandidates: [] as string[],
    }
  }
  const xField = draft.fields.find((field) => field.category === 'core_explanatory')
  const yField = draft.fields.find((field) => field.category === 'target')
  const mFields = draft.fields.filter((field) => field.category === 'candidate_mediator')
  return {
    xVariable: xField?.fieldName ?? '',
    yVariable: yField?.fieldName ?? '',
    mCandidates: mFields
      .map((field) => field.fieldName)
      .filter((fieldName, index, array) => array.indexOf(fieldName) === index),
    displayX: xField ? displayNameForField(xField) : '',
    displayY: yField ? displayNameForField(yField) : '',
    displayMCandidates: mFields
      .map(displayNameForField)
      .filter((displayName, index, array) => array.indexOf(displayName) === index),
  }
}

function sourceFileListMatches(previous: string[], next: string[]): boolean {
  return previous.length === next.length && next.every((fileName) => previous.includes(fileName))
}

function displayNameForField(field: DataDictionaryFieldDraft): string {
  return field.displayName.trim() || field.physicalMeaning.trim() || field.fieldName
}

export function validateDataDictionaryDraft(draft: DataDictionaryDraft | null): string | null {
  if (!draft) {
    return '请先完成数据变量库配置。'
  }

  const physicalMeaningOwners = new Map<string, string>()
  const displayNameOwners = new Map<string, string>()
  for (const field of draft.fields) {
    if (field.category === 'deprecated') {
      continue
    }
    const meaning = field.physicalMeaning.trim()
    if (!meaning) {
      return `字段 ${field.fieldName} 已参与建模配置，请填写对应的物理量名称。`
    }
    const previousOwner = physicalMeaningOwners.get(meaning)
    const currentOwner = `${field.fileName}::${field.fieldName}`
    if (previousOwner && previousOwner !== currentOwner) {
      return `物理量名称“${meaning}”同时绑定到了多个字段，请保持一一对应。`
    }
    physicalMeaningOwners.set(meaning, currentOwner)

    const displayName = field.displayName.trim() || field.physicalMeaning.trim()
    if (!displayName) {
      return `字段 ${field.fieldName} 已参与建模配置，请填写对应的展示名称。`
    }
    const displayOwner = `${field.fileName}::${field.fieldName}`
    if (displayNameOwners.has(displayName) && displayNameOwners.get(displayName) !== displayOwner) {
      return `展示名称“${displayName}”同时绑定到了多个字段，请保持一一对应。`
    }
    displayNameOwners.set(displayName, displayOwner)
  }

  if (!draft.fields.some((field) => field.category === 'core_explanatory')) {
    return '请至少指定一个核心解释变量。'
  }
  if (!draft.fields.some((field) => field.category === 'target')) {
    return '请至少指定一个目标变量。'
  }

  return null
}

function normalizeCategory(value: string): VariableCategory {
  if (value === 'target') {
    return 'target'
  }
  if (value === 'core_explanatory') {
    return 'core_explanatory'
  }
  if (value === 'candidate_mediator') {
    return 'candidate_mediator'
  }
  return 'deprecated'
}
