import { PageTabs } from '../components/PageTabs'
import { useTimelineBundle } from '../hooks/useTimelineBundle'

export function KnowledgeBaseManagerPage() {
  const { data, loading, error } = useTimelineBundle()
  const manager = data?.viewModels.knowledgeBaseManager

  return (
    <div className="timeline-shell">
      <div className="timeline-shell__frame timeline-shell__frame--detail">
        <div className="timeline-topbar">
          <PageTabs />
        </div>

        <section className="workspace-page">
          {loading ? (
            <div className="timeline-empty-state">正在读取知识库状态…</div>
          ) : error || !manager ? (
            <div className="timeline-empty-state timeline-empty-state--error">
              {error ?? '知识库状态不可用。'}
            </div>
          ) : (
            <>
              <header className="workspace-page__header">
                <div>
                  <span className="timeline-header__eyebrow">Knowledge Base Manager</span>
                  <h1>知识库管理页</h1>
                  <p>展示项目信息库、文献知识库、推理痕迹与关键标签。</p>
                </div>
                <div className="detail-page__meta">
                  <div className="status-chip">
                    <span>集合数</span>
                    <strong>{manager.collections.length}</strong>
                  </div>
                  <div className="status-chip">
                    <span>RAG 条目</span>
                    <strong>{manager.ragEntries.length}</strong>
                  </div>
                  <div className="status-chip">
                    <span>标签</span>
                    <strong>{manager.tags.length}</strong>
                  </div>
                  <div className="status-chip">
                    <span>上传记录</span>
                    <strong>{manager.uploads.length}</strong>
                  </div>
                </div>
              </header>

              <div className="workspace-page__grid">
                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Collections</span>
                  <h2>知识集合</h2>
                  <div className="collection-grid">
                    {manager.collections.map((item) => (
                      <article key={item.id} className="collection-card">
                        <strong>{item.label}</strong>
                        <p>{item.summary}</p>
                        <div className="collection-card__meta">
                          <span>{item.status}</span>
                          <span>{item.count} entries</span>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Uploads</span>
                  <h2>知识上传记录</h2>
                  <div className="record-list">
                    {manager.uploads.length > 0 ? (
                      manager.uploads.map((item) => (
                        <article key={item.id} className="record-card">
                          <div className="record-card__header">
                            <strong>{item.fileName}</strong>
                            <span>{item.fileType}</span>
                          </div>
                          <p>{item.note}</p>
                          <div className="collection-card__meta">
                            <span>{item.extractionStatus}</span>
                            <span>{item.syncStatus}</span>
                            <span>{item.uploadedAt ? new Date(item.uploadedAt).toLocaleString() : '--'}</span>
                          </div>
                        </article>
                      ))
                    ) : (
                      <div className="timeline-empty-state">当前会话尚未记录知识上传。已知问题：当前仅支持读取百炼知识库，不支持把本地上传文件回写到百炼托管知识库。</div>
                    )}
                  </div>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">RAG Entries</span>
                  <h2>检索与推理条目</h2>
                  <div className="record-list">
                    {manager.ragEntries.map((item) => (
                      <article key={item.id} className="record-card">
                        <div className="record-card__header">
                          <strong>{item.stage}</strong>
                          <span>{item.id}</span>
                        </div>
                        <p>{item.summary}</p>
                        <div className="collection-card__meta">
                          {item.hypotheses.length > 0 ? <span>{item.hypotheses.join(', ')}</span> : null}
                          {item.uncertainties.length > 0 ? <span>{item.uncertainties.join(', ')}</span> : null}
                        </div>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Models</span>
                  <h2>模型调用清单</h2>
                  <div className="record-list">
                    {manager.modelUsage.map((item) => (
                      <article key={`${item.scope}-${item.model}`} className="record-card">
                        <div className="record-card__header">
                          <strong>{item.scope}</strong>
                          <span>{item.model}</span>
                        </div>
                        <p>{item.purpose}</p>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="detail-card detail-card--wide">
                  <span className="detail-card__eyebrow">Tags</span>
                  <h2>关键标签</h2>
                  <div className="tag-wall">
                    {manager.tags.map((item) => (
                      <span key={item} className="stage-step">
                        {item}
                      </span>
                    ))}
                  </div>
                </section>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
