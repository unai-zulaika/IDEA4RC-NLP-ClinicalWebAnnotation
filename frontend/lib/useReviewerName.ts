'use client'

import { useState, useEffect, useCallback } from 'react'

const STORAGE_KEY = 'reviewerName'

/**
 * Persists the current reviewer's name to localStorage (SSR-safe), mirroring
 * useDefaultCenter. The name is attached to study-review confirmations as a
 * lightweight audit trail — there is no auth in the platform.
 */
export function useReviewerName(): [string, (name: string) => void] {
  const [name, setNameState] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      try {
        return localStorage.getItem(STORAGE_KEY) || ''
      } catch {
        // localStorage unavailable
      }
    }
    return ''
  })

  const setName = useCallback((newName: string) => {
    setNameState(newName)
    try {
      localStorage.setItem(STORAGE_KEY, newName)
    } catch {
      // ignore
    }
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, newValue: newName }))
  }, [])

  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setNameState(e.newValue || '')
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  return [name, setName]
}
