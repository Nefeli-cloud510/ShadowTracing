import type { DataInspectionResult, QuestionAnalysis } from '../api/liveWorkflow'
import { clearDataDictionaryDraft } from './dataDictionaryDraft'

type UploadScope = 'knowledge' | 'data'
export const WORKSPACE_RESET_EVENT = 'shadowtracing:workspace-reset'
export const WORKFLOW_START_PENDING_KEY = 'shadowtracing.workflowStartPending'
export const WORKFLOW_START_ERROR_KEY = 'shadowtracing.workflowStartError'
export const WORKFLOW_START_STATE_EVENT = 'shadowtracing-workflow-start-state'
export const WORKSPACE_RESET_AT_KEY = 'shadowtracing.workspaceResetAt'

export interface MissionControllerDraft {
  question: string
  knowledgeFiles: string[]
  dataFiles: string[]
  submitted: boolean
  questionAnalysis: QuestionAnalysis | null
  confirmedX: string
  confirmedY: string
  confirmedM: string
  questionType: 'forecasting' | 'scientific_inquiry'
  roundFeedback: string
  roundDecision: 'continue' | 'adjust' | 'stop'
  latestInspection: DataInspectionResult | null
  updatedAt?: string
}

const STORAGE_KEY = 'shadowtracing.missionControllerDraft'
const DB_NAME = 'shadowtracing-upload-cache'
const STORE_NAME = 'uploads'
const LEGACY_STORAGE_KEYS = ['st_demo_question', 'st_demo_knowledge_files', 'st_demo_data_files']

function getIndexedDb(): IDBFactory | null {
  return typeof window === 'undefined' ? null : window.indexedDB ?? null
}

async function openDb(): Promise<IDBDatabase | null> {
  const indexedDb = getIndexedDb()
  if (!indexedDb) {
    return null
  }

  return await new Promise((resolve, reject) => {
    const request = indexedDb.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      const database = request.result
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: 'id' })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function readStore<T>(requestFactory: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    openDb()
      .then((database) => {
        if (!database) {
          resolve([] as T)
          return
        }
        const transaction = database.transaction(STORE_NAME, 'readwrite')
        const store = transaction.objectStore(STORE_NAME)
        const request = requestFactory(store)
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error)
        transaction.oncomplete = () => database.close()
      })
      .catch(reject)
  })
}

export function readWorkspaceResetAt(): string | null {
  if (typeof window === 'undefined') {
    return null
  }
  return window.localStorage.getItem(WORKSPACE_RESET_AT_KEY)
}

export function readMissionControllerDraft(): MissionControllerDraft | null {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return null
    }
    const draft = JSON.parse(raw) as MissionControllerDraft
    const resetAt = readWorkspaceResetAt()
    if (!resetAt) {
      return draft
    }
    if (!draft.updatedAt) {
      return null
    }
    return draft.updatedAt > resetAt ? draft : null
  } catch {
    return null
  }
}

export function writeMissionControllerDraft(draft: MissionControllerDraft) {
  if (typeof window === 'undefined') {
    return
  }
  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      ...draft,
      updatedAt: new Date().toISOString(),
    } satisfies MissionControllerDraft),
  )
}

export function clearMissionControllerDraft() {
  if (typeof window === 'undefined') {
    return
  }
  window.localStorage.removeItem(STORAGE_KEY)
}

export function notifyWorkspaceReset() {
  if (typeof window === 'undefined') {
    return
  }
  window.dispatchEvent(new Event(WORKSPACE_RESET_EVENT))
}

export function clearWorkflowStartState() {
  if (typeof window === 'undefined') {
    return
  }
  window.sessionStorage.removeItem(WORKFLOW_START_PENDING_KEY)
  window.sessionStorage.removeItem(WORKFLOW_START_ERROR_KEY)
  window.dispatchEvent(new Event(WORKFLOW_START_STATE_EVENT))
}

export async function persistUploadFiles(scope: UploadScope, files: File[]) {
  const database = await openDb()
  if (!database) {
    return
  }
  const storedAt = new Date().toISOString()

  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, 'readwrite')
    const store = transaction.objectStore(STORE_NAME)
    const cursorRequest = store.openCursor()

    cursorRequest.onsuccess = () => {
      const cursor = cursorRequest.result
      if (!cursor) {
        for (const file of files) {
          store.put({
            id: `${scope}::${file.name}::${file.lastModified}::${file.size}`,
            scope,
            file,
            storedAt,
          })
        }
        return
      }
      if (cursor.value?.scope === scope) {
        cursor.delete()
      }
      cursor.continue()
    }

    cursorRequest.onerror = () => reject(cursorRequest.error)
    transaction.oncomplete = () => {
      database.close()
      resolve()
    }
    transaction.onerror = () => {
      database.close()
      reject(transaction.error)
    }
  })
}

export async function loadUploadFiles(scope: UploadScope): Promise<File[]> {
  const resetAt = readWorkspaceResetAt()
  const records = await readStore<Array<{ scope: UploadScope; file: File; storedAt?: string }>>((store) => store.getAll())
  return (records ?? [])
    .filter((record) => {
      if (record.scope !== scope) {
        return false
      }
      if (!resetAt) {
        return true
      }
      if (!record.storedAt) {
        return false
      }
      return record.storedAt > resetAt
    })
    .map((record) => record.file)
}

export async function clearUploadFiles(scope?: UploadScope) {
  const database = await openDb()
  if (!database) {
    return
  }

  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, 'readwrite')
    const store = transaction.objectStore(STORE_NAME)

    if (!scope) {
      store.clear()
    } else {
      const cursorRequest = store.openCursor()
      cursorRequest.onsuccess = () => {
        const cursor = cursorRequest.result
        if (!cursor) {
          return
        }
        if (cursor.value?.scope === scope) {
          cursor.delete()
        }
        cursor.continue()
      }
      cursorRequest.onerror = () => reject(cursorRequest.error)
    }

    transaction.oncomplete = () => {
      database.close()
      resolve()
    }
    transaction.onerror = () => {
      database.close()
      reject(transaction.error)
    }
  })
}

export async function resetClientWorkspaceState() {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(WORKSPACE_RESET_AT_KEY, new Date().toISOString())
    clearMissionControllerDraft()
    clearDataDictionaryDraft()
    clearWorkflowStartState()
    for (const key of LEGACY_STORAGE_KEYS) {
      window.localStorage.removeItem(key)
    }
  }
  await clearUploadFiles()
  notifyWorkspaceReset()
}

export async function resetHypothesisSpaceClientState() {
  clearWorkflowStartState()
}

export function mergeSelectedFiles(existingFiles: File[], incomingFiles: File[]) {
  const merged = [...existingFiles]
  const seen = new Set(existingFiles.map((file) => `${file.name}::${file.lastModified}::${file.size}`))
  for (const file of incomingFiles) {
    const key = `${file.name}::${file.lastModified}::${file.size}`
    if (seen.has(key)) {
      continue
    }
    merged.push(file)
    seen.add(key)
  }
  return merged
}
