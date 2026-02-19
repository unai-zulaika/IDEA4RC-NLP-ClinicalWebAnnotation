'use client'

import { useState, useEffect, useCallback } from 'react'

const STORAGE_KEY = 'defaultCenter'
const FALLBACK = 'INT'

/**
 * Custom hook that persists the selected center to localStorage.
 * SSR-safe: reads from localStorage only after mount.
 */
export function useDefaultCenter(): [string, (center: string) => void] {
  const [center, setCenterState] = useState<string>(FALLBACK)

  // Hydrate from localStorage after mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) setCenterState(stored)
    } catch {
      // localStorage unavailable (SSR / private browsing)
    }
  }, [])

  const setCenter = useCallback((newCenter: string) => {
    setCenterState(newCenter)
    try {
      localStorage.setItem(STORAGE_KEY, newCenter)
    } catch {
      // ignore
    }
    // Notify other components on the same page
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, newValue: newCenter }))
  }, [])

  // Listen for changes from other components / tabs
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && e.newValue) {
        setCenterState(e.newValue)
      }
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  return [center, setCenter]
}
