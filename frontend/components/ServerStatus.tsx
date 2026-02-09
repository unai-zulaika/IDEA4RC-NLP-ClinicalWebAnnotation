'use client'

import { useEffect, useState } from 'react'
import { serverApi } from '@/lib/api'
import type { ServerStatus, ServerMetrics } from '@/lib/api'

export default function ServerStatus() {
  const [status, setStatus] = useState<ServerStatus | null>(null)
  const [metrics, setMetrics] = useState<ServerMetrics | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadStatus()
    const interval = setInterval(loadStatus, 5000) // Refresh every 5 seconds
    return () => clearInterval(interval)
  }, [])

  const loadStatus = async () => {
    try {
      const [statusData, metricsData] = await Promise.all([
        serverApi.getStatus(),
        serverApi.getMetrics().catch(() => null),
      ])
      setStatus(statusData)
      setMetrics(metricsData)
    } catch (error) {
      console.error('Failed to load server status:', error)
      setStatus({ status: 'error' })
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="text-sm text-gray-500">Loading...</div>
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'available':
        return 'text-green-600'
      case 'unavailable':
      case 'error':
        return 'text-red-600'
      default:
        return 'text-yellow-600'
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'available':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
            Online
          </span>
        )
      case 'unavailable':
      case 'error':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
            Offline
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
            Unknown
          </span>
        )
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-gray-600">Status:</span>
        {getStatusBadge(status?.status || 'unknown')}
      </div>
      {status?.model_name && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-600">Model:</span>
          <span className="text-sm font-medium text-gray-900">
            {status.model_name}
          </span>
        </div>
      )}
      {metrics?.gpu_memory_used_gb !== undefined && metrics?.gpu_memory_used_gb !== null && (
        <div className="mt-4">
          <div className="flex justify-between text-sm mb-1">
            <span className="text-gray-600">GPU Memory</span>
            <span className="text-gray-900">
              {metrics.gpu_memory_used_gb.toFixed(2)} /{' '}
              {metrics.gpu_memory_total_gb !== undefined && metrics.gpu_memory_total_gb !== null
                ? metrics.gpu_memory_total_gb.toFixed(2)
                : '?'} GB
            </span>
          </div>
          {metrics.gpu_memory_total_gb !== undefined && metrics.gpu_memory_total_gb !== null && (
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className="bg-primary-600 h-2 rounded-full"
                style={{
                  width: `${
                    (metrics.gpu_memory_used_gb / metrics.gpu_memory_total_gb) *
                    100
                  }%`,
                }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

