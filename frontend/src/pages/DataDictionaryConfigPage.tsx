import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageTabs } from '../components/PageTabs'
import { inspectStagedDataFiles } from '../api/liveWorkflow'
import {
  mergeDataDictionaryDraft,
  readDataDictionaryDraft,
  validateDataDictionaryDraft,
  writeDataDictionaryDraft,
  type DataDictionaryDraft,
  type VariableCategory,
} from '../utils/dataDictionaryDraft'
import { WORKSPACE_RESET_EVENT } from '../utils/missionControllerPersistence'

const CATEGORY_OPTIONS: Array<{ value: VariableCategory; label: string }> = [
  { value: 'core_explanatory', label: '核心解释变量' },
  { value: 'target', label: '目标变量' },
  { value: 'candidate_mediator', label: '候选特征' },
  { value: 'deprecated', label: '弃用变量' },
]

export function DataDictionaryConfigPage() {
  const navigate = useNavigate()
  const [draft, setDraft] = useState<DataDictionaryDraft | null>(() => readDataDictionaryDraft())
  const [submitMessage, setSubmitMessage] = useState<string | null>(null)

  useEffect(() => {
    const handleWorkspaceReset = () => {
      setDraft(null)
      setSubmitMessage(null)
    }
    window.addEventListener(WORKSPACE_RESET_EVENT, handleWorkspaceReset)
    return () => window.removeEventListener(WORKSPACE_RESET_EVENT, handleWorkspaceReset)
  }, [])

  useEffect(() => {
    let cancelled = false
    async function refreshFromBackendFiles() {
      try {
        const inspection = await inspectStagedDataFiles()
        if (!cancelled && inspection && inspection.tables.length > 0) {
          const nextDraft = mergeDataDictionaryDraft(inspection, readDataDictionaryDraft())
          setDraft(nextDraft)
          writeDataDictionaryDraft(nextDraft)
        }
      } catch {
        // 后端暂存文件不可用时保留本地草稿。
      }
    }
    void refreshFromBackendFiles()
    return () => {
      cancelled = true
    }
  }, [])

  const groupedFields = useMemo(() => {
    const next = new Map<string, DataDictionaryDraft['fields']>()
    for (const field of draft?.fields ?? []) {
      const bucket = next.get(field.fileName) ?? []
      bucket.push(field)
      next.set(field.fileName, bucket)
    }
    return Array.from(next.entries())
  }, [draft?.fields])

  function updateField(fileName: string, fieldName: string, updates: Partial<DataDictionaryDraft['fields'][number]>) {
    if (!draft) {
      return
    }
    const nextDraft = {
      ...draft,
      updatedAt: new Date().toISOString(),
      fields: draft.fields.map((field) =>
        field.fileName === fileName && field.fieldName === fieldName ? { ...field, ...updates } : field,
      ),
    }
    setDraft(nextDraft)
    writeDataDictionaryDraft(nextDraft)
  }

  function updateCategory(fileName: string, fieldName: string, category: VariableCategory) {
    updateField(fileName, fieldName, {
      category,
      physicalMeaning: category === 'deprecated'
        ? ''
        : draft?.fields.find((field) => field.fileName === fileName && field.fieldName === fieldName)?.physicalMeaning ?? '',
    })
  }

  function updatePhysicalMeaning(fileName: string, fieldName: string, value: string) {
    const field = draft?.fields.find((item) => item.fileName === fileName && item.fieldName === fieldName)
    const syncDisplayName = Boolean(
      field && (!field.displayName.trim() || field.displayName === field.physicalMeaning),
    )
    updateField(fileName, fieldName, {
      physicalMeaning: value,
      ...(syncDisplayName ? { displayName: value } : {}),
    })
  }

  function formatDataType(dataType: string): string {
    const normalized = dataType.toLowerCase()
    if (normalized.startsWith('float')) {
      return '浮点数'
    }
    if (normalized.startsWith('int') || normalized.startsWith('uint')) {
      return '整数'
    }
    if (normalized.startsWith('bool')) {
      return '布尔值'
    }
    if (normalized.startsWith('datetime') || normalized.startsWith('timestamp') || normalized.includes('date')) {
      return '日期时间'
    }
    if (
      normalized.startsWith('object') ||
      normalized.startsWith('string') ||
      normalized.startsWith('category') ||
      normalized.startsWith('str')
    ) {
      return '文本'
    }
    if (normalized.startsWith('complex')) {
      return '复数'
    }
    return dataType
  }

  const summary = useMemo(() => {
    const fields = draft?.fields ?? []
    return {
      core: fields.filter((field) => field.category === 'core_explanatory').length,
      target: fields.filter((field) => field.category === 'target').length,
      mediator: fields.filter((field) => field.category === 'candidate_mediator').length,
      deprecated: fields.filter((field) => field.category === 'deprecated').length,
    }
  }, [draft?.fields])

  function handleConfirmSubmit() {
    const validationError = validateDataDictionaryDraft(draft)
    if (validationError) {
      setSubmitMessage(validationError)
      return
    }
    if (draft) {
      const confirmedDraft = {
        ...draft,
        updatedAt: new Date().toISOString(),
        confirmedAt: new Date().toISOString(),
      }
      writeDataDictionaryDraft(confirmedDraft)
    }
    setSubmitMessage('数据变量库已确认，现返回智能体交互控制台。')
    navigate('/dialogue')
  }

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          <header className="workspace-page__header">
            <div>
              <span className="timeline-header__eyebrow">Data Dictionary</span>
              <h1>数据变量库</h1>
              <p>后续假设生成、科学质询与不确定性队列将严格基于这里的选定变量。</p>
            </div>

            <div className="detail-page__meta">
              <div className="status-chip">
                <span>核心解释变量</span>
                <strong>{summary.core}</strong>
              </div>
              <div className="status-chip">
                <span>目标变量</span>
                <strong>{summary.target}</strong>
              </div>
              <div className="status-chip">
                <span>候选特征</span>
                <strong>{summary.mediator}</strong>
              </div>
            </div>
          </header>

          {!draft ? (
            <div className="timeline-empty-state">请先在智能体交互控制台上传实验数据，系统解析表头后才可配置数据变量库。</div>
          ) : (
            <>
              <section className="detail-card detail-card--wide">
                <span className="detail-card__eyebrow">Configuration Summary</span>
                <h2>当前配置摘要</h2>
                <div className="metrics-grid metrics-grid--two">
                  <div className="metric-box">
                    <span className="metric-box__label">时间列</span>
                    <span className="metric-box__value">{draft.timeColumn || '--'}</span>
                  </div>
                  <div className="metric-box">
                    <span className="metric-box__label">总字段数</span>
                    <span className="metric-box__value">{draft.fields.length}</span>
                  </div>
                  <div className="metric-box">
                    <span className="metric-box__label">弃用变量</span>
                    <span className="metric-box__value">{summary.deprecated}</span>
                  </div>
                  <div className="metric-box metric-box--highlight">
                    <span className="metric-box__label">最近更新</span>
                    <span className="metric-box__value">{new Date(draft.updatedAt).toLocaleTimeString()}</span>
                  </div>
                </div>
              </section>

              {groupedFields.map(([fileName, fields]) => (
                <section key={fileName} className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Source Table</span>
                  <h2>{fileName}</h2>
                  <div className="data-dictionary-table">
                    <div className="data-dictionary-table__row data-dictionary-table__row--header">
                      <span>表头字段</span>
                      <span>数据类型</span>
                      <span>缺失率</span>
                      <span>变量类别</span>
                      <span>物理量名称</span>
                      <span>展示名称</span>
                    </div>
                    {fields.map((field) => (
                      <div key={`${fileName}-${field.fieldName}`} className="data-dictionary-table__row">
                        <span className="data-dictionary-table__field">
                          <strong>{field.fieldName}</strong>
                        </span>
                        <span>{formatDataType(field.dataType)}</span>
                        <span>{(field.missingRate * 100).toFixed(1)}%</span>
                        <select
                          className="controller-inline-input"
                          value={field.category}
                          onChange={(event) => updateCategory(fileName, field.fieldName, event.target.value as VariableCategory)}
                        >
                          {CATEGORY_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                        <input
                          className="controller-inline-input"
                          value={field.physicalMeaning}
                          onChange={(event) => updatePhysicalMeaning(fileName, field.fieldName, event.target.value)}
                          placeholder={field.category === 'deprecated' ? '弃用字段无需填写物理量名称' : '请填写物理量名称，例如太阳风速度'}
                          disabled={field.category === 'deprecated'}
                        />
                        <input
                          className="controller-inline-input"
                          value={field.displayName}
                          onChange={(event) => updateField(fileName, field.fieldName, { displayName: event.target.value })}
                          placeholder={field.category === 'deprecated' ? '弃用字段暂不展示' : '填写面向 LLM 与前端展示的名称，例如太阳风速度'}
                          disabled={field.category === 'deprecated'}
                        />
                      </div>
                    ))}
                  </div>
                </section>
              ))}

              <div className="detail-links">
                <button type="button" className="detail-link detail-link--button detail-link--panel-button" onClick={handleConfirmSubmit}>
                  确认提交
                </button>
                <button type="button" className="detail-link detail-link--button detail-link--panel-button" onClick={() => navigate('/dialogue')}>
                  返回智能体交互控制台
                </button>
              </div>
              {submitMessage ? <div className="timeline-empty-state">{submitMessage}</div> : null}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
