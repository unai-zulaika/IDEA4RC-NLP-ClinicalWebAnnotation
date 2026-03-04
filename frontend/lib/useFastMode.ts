'use client'

import { useState, useEffect, useCallback } from 'react'

const STORAGE_KEY = 'fastMode'

/**
 * Custom hook that persists the fast mode toggle to localStorage.
 * SSR-safe: reads from localStorage synchronously via lazy initializer.
 */
export function useFastMode(): [boolean, (enabled: boolean) => void] {
  const [fastMode, setFastModeState] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      try {
        const stored = localStorage.getItem(STORAGE_KEY)
        if (stored !== null) return stored === 'true'
      } catch {
        // localStorage unavailable
      }
    }
    return false
  })

  const setFastMode = useCallback((enabled: boolean) => {
    setFastModeState(enabled)
    try {
      localStorage.setItem(STORAGE_KEY, String(enabled))
    } catch {
      // ignore
    }
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, newValue: String(enabled) }))
  }, [])

  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && e.newValue !== null) {
        setFastModeState(e.newValue === 'true')
      }
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  return [fastMode, setFastMode]
}
