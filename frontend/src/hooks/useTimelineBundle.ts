import { useEffect, useRef, useState } from 'react'
import { loadTimelineBundle } from '../data/realStateLoader'
import type { TimelineDataBundle } from '../types/timeline'

interface TimelineBundleState {
  data: TimelineDataBundle | null
  loading: boolean
  refreshing: boolean
  error: string | null
}

export function useTimelineBundle() {
  const [state, setState] = useState<TimelineBundleState>({
    data: null,
    loading: true,
    refreshing: false,
    error: null,
  })
  const latestDataRef = useRef<TimelineDataBundle | null>(null)

  useEffect(() => {
    let isMounted = true
    let intervalId: number | null = null

    async function load(isRefresh = false) {
      if (isRefresh && isMounted) {
        setState((current) => ({
          ...current,
          refreshing: true,
          error: null,
        }))
      }

      try {
        const data = await loadTimelineBundle()
        latestDataRef.current = data
        if (isMounted) {
          setState({
            data,
            loading: false,
            refreshing: false,
            error: null,
          })
        }
      } catch (error) {
        if (isMounted) {
          setState((current) => ({
            data: current.data,
            loading: false,
            refreshing: false,
            error: error instanceof Error ? error.message : 'Failed to load timeline data',
          }))
        }
      }
    }

    void load()
    intervalId = window.setInterval(() => {
      if (document.hidden) {
        return
      }
      void load(false)
    }, 8000)

    return () => {
      isMounted = false
      if (intervalId) {
        window.clearInterval(intervalId)
      }
    }
  }, [])

  async function refresh() {
    setState((current) => ({
      ...current,
      refreshing: true,
      error: null,
    }))

    try {
      const data = await loadTimelineBundle()
      setState({
        data,
        loading: false,
        refreshing: false,
        error: null,
      })
    } catch (error) {
      setState((current) => ({
        ...current,
        refreshing: false,
        error: error instanceof Error ? error.message : 'Failed to refresh timeline data',
      }))
    }
  }

  return {
    ...state,
    refresh,
  }
}
