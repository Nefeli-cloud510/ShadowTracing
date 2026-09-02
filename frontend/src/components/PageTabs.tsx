import { Link } from 'react-router-dom'
import { useTabs } from '../contexts/TabContext'

export function PageTabs() {
  const { tabs, removeTab, activeTabId } = useTabs()

  return (
    <div className="page-tabs">
      {tabs.map((tab) => (
        <div
          key={tab.id}
          className={['page-tab', activeTabId === tab.id ? 'page-tab--active' : '', tab.id !== 'home' ? 'page-tab--closable' : ''].filter(Boolean).join(' ')}
        >
          <Link to={tab.path} className="page-tab__link">
            {tab.title}
          </Link>
          {tab.id !== 'home' && (
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
