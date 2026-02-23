'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { promptsApi } from '@/lib/api'
import { useDefaultCenter } from '@/lib/useDefaultCenter'

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
        ? 'border-primary-500 text-gray-900'
        : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
    }`
  }

  return (
    <nav className="bg-white shadow-sm border-b">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          <div className="flex">
            <div className="flex-shrink-0 flex items-center">
              <h1 className="text-xl font-bold text-gray-900">
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

          {/* Global center selector */}
          {centers.length > 0 && (
            <div className="flex items-center">
              <label className="text-sm text-gray-500 mr-2">Center:</label>
              <select
                value={center}
                onChange={(e) => setCenter(e.target.value)}
                className="px-2 py-1 border border-gray-300 rounded-md text-sm bg-white"
              >
                {centers.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}
