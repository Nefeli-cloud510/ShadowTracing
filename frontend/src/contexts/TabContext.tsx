import React, { createContext, useContext, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'

export interface Tab {
  id: string
  title: string
  path: string
}

interface TabContextType {
  tabs: Tab[]
  addTab: (tab: Tab) => void
  removeTab: (id: string) => void
  activeTabId: string
}

const TabContext = createContext<TabContextType | null>(null)

export function TabProvider({ children }: { children: React.ReactNode }) {
  const [tabs, setTabs] = useState<Tab[]>([{ id: 'home', title: '首页 Timeline', path: '/' }])
  const location = useLocation()
  const navigate = useNavigate()

  const activeTabId = tabs.find((t) => t.path === location.pathname)?.id || 'home'

  const addTab = (tab: Tab) => {
    setTabs((prev) => {
      if (!prev.find((t) => t.id === tab.id)) {
        return [...prev, tab]
      }
      return prev
    })
    navigate(tab.path)
  }

  const removeTab = (id: string) => {
    if (id === 'home') return
    setTabs((prev) => {
      const newTabs = prev.filter((t) => t.id !== id)
      if (activeTabId === id) {
        navigate(newTabs[newTabs.length - 1].path)
      }
      return newTabs
    })
  }

  return (
    <TabContext.Provider value={{ tabs, addTab, removeTab, activeTabId }}>
      {children}
    </TabContext.Provider>
  )
}

export function useTabs() {
  const context = useContext(TabContext)
  if (!context) throw new Error('useTabs must be used within TabProvider')
  return context
}
