'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { promptsApi } from '@/lib/api'
import { useDefaultCenter } from '@/lib/useDefaultCenter'
import ThemeToggle from './ThemeToggle'

export default function Navbar() {
  const pathname = usePathname()
  const [center, setCenter] = useDefaultCenter()
  const [centers, setCenters] = useState<string[]>([])

  useEffect(() => {
    promptsApi.listCenters().then(setCenters).catch(console.error)
  }, [])

  // If stored center isn't in the available list, fall back to first available
  useEffect(() => {
    if (centers.length > 0 && !centers.includes(center)) {
      setCenter(centers[0])
    }
  }, [centers, center, setCenter])

  const linkClass = (href: string) => {
    const active = pathname === href
    return `inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium ${
      active
        ? 'border-primary-500 text-gray-900 dark:text-gray-100'
        : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:border-gray-600 dark:hover:text-gray-200'
    }`
  }

  return (
    <nav className="bg-white shadow-sm border-b border-gray-200 dark:bg-gray-800 dark:border-gray-700">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16 gap-3">
          <div className="flex min-w-0">
            <div className="flex min-w-0 items-center">
              <h1 className="truncate text-base font-bold text-gray-900 dark:text-gray-100 sm:text-xl">
                Clinical Data Curation
              </h1>
            </div>
            <div className="hidden sm:ml-6 sm:flex sm:space-x-8">
              <Link href="/" className={linkClass('/')}>
                Dashboard
              </Link>
              <Link href="/prompts" className={linkClass('/prompts')}>
                Prompts
              </Link>
              <Link href="/presets" className={linkClass('/presets')}>
                Presets
              </Link>
              <Link href="/upload" className={linkClass('/upload')}>
                Upload
              </Link>
            </div>
          </div>

          <div className="flex flex-shrink-0 items-center gap-2 sm:gap-3">
            {centers.length > 0 && (
              <div className="flex items-center">
                <label className="mr-2 hidden text-sm text-gray-500 dark:text-gray-400 sm:inline">Center:</label>
                <select
                  value={center}
                  onChange={(e) => setCenter(e.target.value)}
                  className="max-w-[40vw] rounded-md border border-gray-300 px-2 py-1 text-sm bg-white dark:border-gray-600 dark:text-gray-100 dark:bg-gray-800 sm:max-w-none"
                >
                  {centers.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
            )}
            <ThemeToggle />
          </div>
        </div>
      </div>
    </nav>
  )
}
