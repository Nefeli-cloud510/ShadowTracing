import { useEffect, useState } from 'react'
import { loadTimelineBundle } from '../data/realStateLoader'
import type { TimelineDataBundle } from '../types/timeline'

interface TimelineBundleState {
  data: TimelineDataBundle | null
  loading: boolean
  error: string | null
}

export function useTimelineBundle() {
  const [state, setState] = useState<TimelineBundleState>({
    data: null,
    loading: true,
    error: null,
  })

  useEffect(() => {
    let isMounted = true

    async function load() {
      try {
        const data = await loadTimelineBundle()
        if (isMounted) {
          setState({ data, loading: false, error: null })
        }
      } catch (error) {
        if (isMounted) {
          setState({
            data: null,
            loading: false,
            error: error instanceof Error ? error.message : 'Failed to load timeline data',
          })
        }
      }
    }

    void load()

    return () => {
      isMounted = false
    }
  }, [])

  return state
}
