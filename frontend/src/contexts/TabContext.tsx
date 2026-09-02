import React, { createContext, useContext, useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import type { CorePageId } from '../types/timeline'

export interface Tab {
  id: string
  title: string
  path: string
  pageId?: CorePageId
  roundId?: string
  nodeId?: string
}

interface TabContextType {
  tabs: Tab[]
  addTab: (tab: Tab) => void
  removeTab: (id: string) => void
  activeTabId: string
  setActiveTabId: (id: string) => void
}

const TabContext = createContext<TabContextType | null>(null)

const CORE_TABS: Tab[] = [
  { id: 'workflow', title: '主流程', path: '/workflow', pageId: 'workflow' },
  { id: 'dialogue', title: '智能体交互控制台', path: '/dialogue', pageId: 'dialogue' },
  { id: 'data-dictionary', title: '数据字典配置', path: '/data-dictionary', pageId: 'data-dictionary' },
  { id: 'hypotheses', title: '科学假设生成', path: '/hypotheses', pageId: 'hypotheses' },
  { id: 'uncertainties', title: '不确定性识别', path: '/uncertainties', pageId: 'uncertainties' },
  { id: 'approval', title: '候选实验审批', path: '/approval', pageId: 'approval' },
  { id: 'execution', title: '实验执行', path: '/execution', pageId: 'execution' },
  { id: 'report', title: '轮次报告', path: '/report', pageId: 'report' },
]

function buildNodeTab(pathname: string): Tab | null {
  const match = pathname.match(/^\/node\/([^/]+)\/([^/]+)$/)
  if (!match) {
    return null
  }

  const [, roundId, nodeId] = match
  const decodedNodeId = decodeURIComponent(nodeId)
  return {
    id: `node-${roundId}-${nodeId}`,
    title: `${decodedNodeId} 详情`,
    path: pathname,
    roundId,
    nodeId,
  }
}

export function TabProvider({ children }: { children: React.ReactNode }) {
  const [tabs, setTabs] = useState<Tab[]>(CORE_TABS)
  const [activeTabId, setActiveTabId] = useState('workflow')
  const navigate = useNavigate()
  const location = useLocation()

  // 同步 URL 到 activeTab
  useEffect(() => {
    const nodeTab = buildNodeTab(location.pathname)
    if (nodeTab) {
      setTabs((prev) => {
        if (prev.some((item) => item.id === nodeTab.id)) {
          return prev
        }
        return [...prev, nodeTab]
      })
      setActiveTabId(nodeTab.id)
      return
    }

    const currentTab = tabs.find(t => t.path === location.pathname)
    if (currentTab) {
      setActiveTabId(currentTab.id)
    } else if (location.pathname === '/') {
      setActiveTabId('workflow')
    }
  }, [location.pathname, tabs])

  const setActiveTab = (id: string) => {
    const target = tabs.find((tab) => tab.id === id)
    if (!target) {
      return
    }

    setActiveTabId(id)
    navigate(target.path)
  }

  const addTab = (tab: Tab) => {
    setTabs((prev) => {
      if (!prev.find((t) => t.id === tab.id)) {
        return [...prev, tab]
      }
      return prev
    })
    setActiveTabId(tab.id)
    navigate(tab.path)
  }

  const removeTab = (id: string) => {
    if (CORE_TABS.some((item) => item.id === id)) return
    setTabs((prev) => {
      const newTabs = prev.filter((t) => t.id !== id)
      if (activeTabId === id) {
        navigate(newTabs[newTabs.length - 1].path)
      }
      return newTabs
    })
  }

  return (
    <TabContext.Provider value={{ tabs, addTab, removeTab, activeTabId, setActiveTabId: setActiveTab }}>
      {children}
    </TabContext.Provider>
  )
}

export function useTabs() {
  const context = useContext(TabContext)
  if (!context) throw new Error('useTabs must be used within TabProvider')
  return context
}
