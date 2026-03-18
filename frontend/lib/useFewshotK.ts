'use client'

import { useState, useCallback } from 'react'

const STANDARD_KEY = 'fewshotKStandard'
const FAST_KEY = 'fewshotKFast'
const DEFAULT_STANDARD = 3
const DEFAULT_FAST = 1

function readFromStorage(key: string, defaultValue: number): number {
  if (typeof window !== 'undefined') {
    try {
      const stored = localStorage.getItem(key)
      if (stored !== null) {
        const parsed = parseInt(stored, 10)
        if (!isNaN(parsed) && parsed >= 1) return parsed
      }
    } catch {
      // localStorage unavailable
    }
  }
  return defaultValue
}

export function useFewshotK() {
  const [standardK, setStandardKState] = useState<number>(() =>
    readFromStorage(STANDARD_KEY, DEFAULT_STANDARD)
  )
  const [fastK, setFastKState] = useState<number>(() =>
    readFromStorage(FAST_KEY, DEFAULT_FAST)
  )

  const setStandardK = useCallback((k: number) => {
    const clamped = Math.max(1, Math.min(10, k))
    setStandardKState(clamped)
    try { localStorage.setItem(STANDARD_KEY, String(clamped)) } catch {}
  }, [])

  const setFastK = useCallback((k: number) => {
    const clamped = Math.max(1, Math.min(5, k))
    setFastKState(clamped)
    try { localStorage.setItem(FAST_KEY, String(clamped)) } catch {}
  }, [])

  return { standardK, setStandardK, fastK, setFastK }
}
