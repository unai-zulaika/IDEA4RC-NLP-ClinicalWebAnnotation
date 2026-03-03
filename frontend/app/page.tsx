'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { serverApi, sessionsApi } from '@/lib/api'
import type { ServerMetrics, SessionInfo } from '@/lib/api'
import ServerStatus from '@/components/ServerStatus'

export default function Dashboard() {
  const router = useRouter()
  const importInputRef = useRef<HTMLInputElement>(null)
  const [metrics, setMetrics] = useState<ServerMetrics | null>(null)
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 5000) // Refresh every 5 seconds
    return () => clearInterval(interval)
  }, [])

  const loadData = async () => {
    try {
      const [metricsData, sessionsData] = await Promise.all([
        serverApi.getMetrics().catch(() => null),
        sessionsApi.list().catch(() => []),
      ])
      setMetrics(metricsData)
      setSessions(sessionsData)
    } catch (error) {
      console.error('Failed to load dashboard data:', error)
    } finally {
      setLoading(false)
    }
  }

  const totalNotes = sessions.reduce((sum, s) => sum + s.note_count, 0)

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()

    if (!confirm('Are you sure you want to delete this session? This action cannot be undone.')) {
      return
    }

    setDeletingSessionId(sessionId)
    try {
      await sessionsApi.delete(sessionId)
      await loadData() // Reload sessions
    } catch (error: any) {
      alert(`Failed to delete session: ${error.response?.data?.detail || error.message}`)
    } finally {
      setDeletingSessionId(null)
    }
  }

  const handleImportSession = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    try {
      const session = await sessionsApi.importSession(file)
      router.push(`/annotate/${session.session_id}`)
    } catch (error: any) {
      alert(`Failed to import session: ${error.response?.data?.detail || error.message}`)
    } finally {
      setImporting(false)
      e.target.value = ''
    }
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <div>
          <input
            ref={importInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleImportSession}
          />
          <button
            onClick={() => importInputRef.current?.click()}
            disabled={importing}
            className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
          >
            {importing ? 'Importing...' : 'Import Session'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-700 mb-2">
            LLM Server Status (vLLM)
          </h2>
          <ServerStatus />
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-700 mb-2">
            Total Notes
          </h2>
          <p className="text-3xl font-bold text-primary-600">{totalNotes}</p>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-700 mb-2">
            Active Sessions
          </h2>
          <p className="text-3xl font-bold text-primary-600">{sessions.length}</p>
        </div>
      </div>

      {metrics && (
        <div className="bg-white rounded-lg shadow p-6 mb-8">
          <h2 className="text-lg font-semibold text-gray-700 mb-4">
            Server Metrics
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {metrics.gpu_memory_used_gb !== undefined && metrics.gpu_memory_used_gb !== null && (
              <div>
                <p className="text-sm text-gray-500">GPU Memory Used</p>
                <p className="text-xl font-semibold">
                  {metrics.gpu_memory_used_gb.toFixed(2)} GB
                  {metrics.gpu_memory_total_gb !== undefined && metrics.gpu_memory_total_gb !== null &&
                    ` / ${metrics.gpu_memory_total_gb.toFixed(2)} GB`}
                </p>
              </div>
            )}
            {metrics.throughput_tokens_per_sec !== undefined && metrics.throughput_tokens_per_sec !== null && (
              <div>
                <p className="text-sm text-gray-500">Throughput</p>
                <p className="text-xl font-semibold">
                  {metrics.throughput_tokens_per_sec.toFixed(1)} tokens/s
                </p>
              </div>
            )}
            {metrics.active_requests !== undefined && (
              <div>
                <p className="text-sm text-gray-500">Active Requests</p>
                <p className="text-xl font-semibold">
                  {metrics.active_requests}
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="bg-white rounded-lg shadow">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-700">
            Recent Sessions
          </h2>
        </div>
        <div className="divide-y divide-gray-200">
          {loading ? (
            <div className="px-6 py-4 text-center text-gray-500">
              Loading...
            </div>
          ) : sessions.length === 0 ? (
            <div className="px-6 py-4 text-center text-gray-500">
              No sessions yet. <Link href="/upload" className="text-primary-600 hover:underline">Upload a CSV</Link> to get started.
            </div>
          ) : (
            sessions.slice(0, 10).map((session) => (
              <div
                key={session.session_id}
                className="px-6 py-4 hover:bg-gray-50 transition-colors"
              >
                <div className="flex justify-between items-center">
                  <Link
                    href={`/annotate/${session.session_id}`}
                    className="flex-1"
                  >
                    <div>
                      <h3 className="text-sm font-medium text-gray-900">
                        {session.name}
                      </h3>
                      <p className="text-sm text-gray-500">
                        {session.note_count} notes • {session.prompt_types.length} prompt types
                      </p>
                    </div>
                  </Link>
                  <div className="flex items-center gap-4">
                    <div className="text-sm text-gray-500">
                      {new Date(session.updated_at).toLocaleDateString()}
                    </div>
                    <button
                      onClick={(e) => handleDeleteSession(session.session_id, e)}
                      disabled={deletingSessionId === session.session_id}
                      className="text-red-600 hover:text-red-800 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
                      title="Delete session"
                    >
                      {deletingSessionId === session.session_id ? 'Deleting...' : 'Delete'}
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

