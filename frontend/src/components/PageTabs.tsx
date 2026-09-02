import { useTabs } from '../contexts/TabContext'

export function PageTabs() {
  const { tabs, removeTab, activeTabId, setActiveTabId } = useTabs()

  return (
    <div className="page-tabs">
      {tabs.map((tab) => (
        <div
          key={tab.id}
          className={['page-tab', activeTabId === tab.id ? 'page-tab--active' : '', !tab.pageId ? 'page-tab--closable' : ''].filter(Boolean).join(' ')}
        >
          <button
            type="button"
            className="page-tab__link"
            onClick={() => setActiveTabId(tab.id)}
          >
            {tab.title}
          </button>
          {!tab.pageId && (
            <button
              type="button"
              className="page-tab__close"
              onClick={(e) => {
                e.preventDefault()
                removeTab(tab.id)
              }}
              aria-label="Close tab"
            >
              ×
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
