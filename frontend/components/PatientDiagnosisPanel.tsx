'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  sessionsApi,
  annotateApi,
  DiagnosisValidationReport,
  PatientDiagnosisInfo,
  SessionData,
} from '@/lib/api'

interface PatientDiagnosisPanelProps {
  sessionId: string
  session: SessionData
  onDiagnosisUpdate?: () => void
  onNavigateToAnnotation?: (noteId: string, promptType: string) => void
}

export default function PatientDiagnosisPanel({
  sessionId,
  onDiagnosisUpdate,
  onNavigateToAnnotation,
}: PatientDiagnosisPanelProps) {
  const [report, setReport] = useState<DiagnosisValidationReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [resolving, setResolving] = useState<Record<string, boolean>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [searchQuery, setSearchQuery] = useState<Record<string, string>>({})
  const [searchResults, setSearchResults] = useState<
    Record<string, Array<{ query_code: string; name: string; morphology_code: string; topography_code: string }>>
  >({})
  const [searching, setSearching] = useState<Record<string, boolean>>({})

  const fetchDiagnoses = useCallback(async () => {
    setLoading(true)
    try {
      const data = await sessionsApi.getDiagnoses(sessionId)
      setReport(data)
    } catch (err) {
      console.error('Failed to fetch diagnoses:', err)
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => {
    fetchDiagnoses()
  }, [fetchDiagnoses])

  const handleResolveAll = async () => {
    setLoading(true)
    try {
      const data = await sessionsApi.resolveAllDiagnoses(sessionId)
      setReport(data)
      onDiagnosisUpdate?.()
    } catch (err) {
      console.error('Failed to resolve all:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = async (patientId: string) => {
    const q = searchQuery[patientId]?.trim()
    if (!q) return
    setSearching(prev => ({ ...prev, [patientId]: true }))
    try {
      const results = await annotateApi.searchICDO3Codes(q)
      setSearchResults(prev => ({ ...prev, [patientId]: results.results || [] }))
    } catch (err) {
      console.error('Search failed:', err)
    } finally {
      setSearching(prev => ({ ...prev, [patientId]: false }))
    }
  }

  const handleSelectCode = async (patientId: string, queryCode: string) => {
    setResolving(prev => ({ ...prev, [patientId]: true }))
    try {
      await sessionsApi.resolvePatientDiagnosis(sessionId, patientId, queryCode)
      await fetchDiagnoses()
      setSearchResults(prev => ({ ...prev, [patientId]: [] }))
      setSearchQuery(prev => ({ ...prev, [patientId]: '' }))
      onDiagnosisUpdate?.()
    } catch (err) {
      alert(`Failed to resolve: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setResolving(prev => ({ ...prev, [patientId]: false }))
    }
  }

  const toggleExpand = (pid: string) => {
    setExpanded(prev => ({ ...prev, [pid]: !prev[pid] }))
  }

  if (loading && !report) {
    return (
      <div className="p-4 text-sm text-gray-500">Loading patient diagnoses...</div>
    )
  }

  if (!report) return null

  const needsReview = report.patients.filter(p => p.status === 'needs_review')
  const resolved = report.patients.filter(
    p => p.status === 'auto_resolved' || p.status === 'manually_resolved'
  )
  const skipped = report.patients.filter(p => p.status === 'skipped')

  return (
    <div className="border rounded-lg bg-white shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-3">
          <h3 className="font-semibold text-gray-900">Patient Diagnoses</h3>
          <div className="flex gap-2 text-xs">
            {resolved.length > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-green-100 text-green-700">
                {resolved.length} resolved
              </span>
            )}
            {needsReview.length > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700">
                {needsReview.length} needs review
              </span>
            )}
            {skipped.length > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
                {skipped.length} skipped
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleResolveAll}
            disabled={loading}
            className="px-3 py-1.5 text-xs font-medium bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50"
          >
            {loading ? 'Resolving...' : 'Resolve All'}
          </button>
          <button
            onClick={fetchDiagnoses}
            disabled={loading}
            className="px-3 py-1.5 text-xs font-medium border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Patient List */}
      <div className="divide-y max-h-96 overflow-y-auto">
        {/* Needs Review first */}
        {needsReview.map(patient => (
          <PatientRow
            key={patient.patient_id}
            patient={patient}
            isExpanded={!!expanded[patient.patient_id]}
            onToggle={() => toggleExpand(patient.patient_id)}
            searchQuery={searchQuery[patient.patient_id] || ''}
            onSearchQueryChange={(val) =>
              setSearchQuery(prev => ({ ...prev, [patient.patient_id]: val }))
            }
            onSearch={() => handleSearch(patient.patient_id)}
            searchResults={searchResults[patient.patient_id] || []}
            isSearching={!!searching[patient.patient_id]}
            isResolving={!!resolving[patient.patient_id]}
            onSelectCode={(code) => handleSelectCode(patient.patient_id, code)}
            onNavigateToAnnotation={onNavigateToAnnotation}
          />
        ))}
        {/* Resolved */}
        {resolved.map(patient => (
          <PatientRow
            key={patient.patient_id}
            patient={patient}
            isExpanded={!!expanded[patient.patient_id]}
            onToggle={() => toggleExpand(patient.patient_id)}
            searchQuery=""
            onSearchQueryChange={() => {}}
            onSearch={() => {}}
            searchResults={[]}
            isSearching={false}
            isResolving={false}
            onSelectCode={() => {}}
            onNavigateToAnnotation={onNavigateToAnnotation}
          />
        ))}
        {/* Skipped (collapsed summary) */}
        {skipped.length > 0 && (
          <div className="px-4 py-2 text-xs text-gray-400">
            {skipped.length} patient(s) with no diagnosis annotations (skipped)
          </div>
        )}
      </div>
    </div>
  )
}

interface PatientRowProps {
  patient: PatientDiagnosisInfo
  isExpanded: boolean
  onToggle: () => void
  searchQuery: string
  onSearchQueryChange: (val: string) => void
  onSearch: () => void
  searchResults: Array<{ query_code: string; name: string; morphology_code: string; topography_code: string }>
  isSearching: boolean
  isResolving: boolean
  onSelectCode: (code: string) => void
  onNavigateToAnnotation?: (noteId: string, promptType: string) => void
}

function PatientRow({
  patient,
  isExpanded,
  onToggle,
  searchQuery,
  onSearchQueryChange,
  onSearch,
  searchResults,
  isSearching,
  isResolving,
  onSelectCode,
  onNavigateToAnnotation,
}: PatientRowProps) {
  const statusConfig = {
    auto_resolved: { color: 'text-green-600', bg: 'bg-green-50', icon: '\u2713', label: 'Auto-resolved' },
    manually_resolved: { color: 'text-blue-600', bg: 'bg-blue-50', icon: '\u2713', label: 'Manually resolved' },
    needs_review: { color: 'text-yellow-600', bg: 'bg-yellow-50', icon: '!', label: 'Needs review' },
    skipped: { color: 'text-gray-400', bg: 'bg-gray-50', icon: '-', label: 'Skipped' },
  }
  const cfg = statusConfig[patient.status] || statusConfig.skipped

  return (
    <div className={`${cfg.bg}`}>
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-2.5 text-sm hover:bg-black/5 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className={`font-bold ${cfg.color} w-5 text-center`}>{cfg.icon}</span>
          <span className="font-mono text-xs text-gray-700">{patient.patient_id}</span>
          <span className={`text-xs ${cfg.color}`}>{cfg.label}</span>
        </div>
        <span className="text-gray-400 text-xs">{isExpanded ? '\u25B2' : '\u25BC'}</span>
      </button>

      {isExpanded && (
        <div className="px-4 pb-3 space-y-2 text-xs">
          {/* Histology codes */}
          {patient.histology_codes.length > 0 && (
            <div className="space-y-0.5">
              <span className="font-medium text-gray-600">Histology: </span>
              {patient.histology_codes.map((h, i) => (
                <button
                  key={i}
                  className="flex items-center gap-1.5 ml-1 group cursor-pointer hover:bg-purple-50 rounded px-1 -mx-1 transition-colors text-left"
                  onClick={() => h.prompt_type && onNavigateToAnnotation?.(h.note_id, h.prompt_type)}
                  title={`Go to annotation (note ${h.note_id})`}
                >
                  <span className="inline-block px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded font-mono shrink-0 group-hover:bg-purple-200 transition-colors">
                    {h.code}
                  </span>
                  {h.description && (
                    <span className="text-gray-500 truncate group-hover:text-purple-600 transition-colors">{h.description}</span>
                  )}
                  <span className="text-gray-300 group-hover:text-purple-500 shrink-0 transition-colors">&rarr;</span>
                </button>
              ))}
            </div>
          )}

          {/* Topography codes */}
          {patient.topography_codes.length > 0 && (
            <div className="space-y-0.5">
              <span className="font-medium text-gray-600">Topography: </span>
              {patient.topography_codes.map((t, i) => (
                <button
                  key={i}
                  className="flex items-center gap-1.5 ml-1 group cursor-pointer hover:bg-teal-50 rounded px-1 -mx-1 transition-colors text-left"
                  onClick={() => t.prompt_type && onNavigateToAnnotation?.(t.note_id, t.prompt_type)}
                  title={`Go to annotation (note ${t.note_id})`}
                >
                  <span className="inline-block px-1.5 py-0.5 bg-teal-100 text-teal-700 rounded font-mono shrink-0 group-hover:bg-teal-200 transition-colors">
                    {t.code}
                  </span>
                  {t.description && (
                    <span className="text-gray-500 truncate group-hover:text-teal-600 transition-colors">{t.description}</span>
                  )}
                  <span className="text-gray-300 group-hover:text-teal-500 shrink-0 transition-colors">&rarr;</span>
                </button>
              ))}
            </div>
          )}

          {/* Review reasons */}
          {patient.review_reasons.length > 0 && (
            <div className="text-yellow-700">
              {patient.review_reasons.map((r, i) => (
                <div key={i}>- {r}</div>
              ))}
            </div>
          )}

          {/* Resolved code */}
          {patient.resolved_code && (
            <div className="p-2 bg-white rounded border border-green-200 space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium text-green-700">ICD-O-3:</span>
                <span className="font-mono text-sm">{patient.resolved_code.query_code}</span>
                {patient.resolved_code.name && patient.resolved_code.name !== patient.resolved_code.query_code && (
                  <span className="text-gray-600 truncate">
                    — {patient.resolved_code.name}
                  </span>
                )}
              </div>
              {patient.csv_id && (
                <div className="flex items-center gap-2 text-gray-500">
                  <span className="font-medium">CSV ID:</span>
                  <span className="font-mono">{patient.csv_id}</span>
                </div>
              )}
            </div>
          )}

          {/* Manual resolution UI (only for needs_review) */}
          {patient.status === 'needs_review' && (
            <div className="mt-2 p-2 bg-white rounded border border-yellow-200 space-y-2">
              <div className="font-medium text-gray-700">Manual Resolution</div>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={e => onSearchQueryChange(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && onSearch()}
                  placeholder="Search ICD-O-3 codes..."
                  className="flex-1 px-2 py-1 border rounded text-xs focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
                <button
                  onClick={onSearch}
                  disabled={isSearching}
                  className="px-2 py-1 bg-primary-600 text-white rounded text-xs hover:bg-primary-700 disabled:opacity-50"
                >
                  {isSearching ? '...' : 'Search'}
                </button>
              </div>

              {searchResults.length > 0 && (
                <div className="max-h-48 overflow-y-auto border rounded divide-y">
                  {searchResults.map((r, i) => (
                    <button
                      key={i}
                      onClick={() => onSelectCode(r.query_code)}
                      disabled={isResolving}
                      className="w-full text-left px-2 py-1.5 hover:bg-primary-50 disabled:opacity-50"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-primary-700 whitespace-nowrap">
                          {r.query_code}
                        </span>
                        {r.name && r.name !== r.query_code && (
                          <span className="text-gray-600 truncate">{r.name}</span>
                        )}
                      </div>
                      <div className="flex gap-3 text-[10px] text-gray-400 mt-0.5">
                        <span>Morph: {r.morphology_code}</span>
                        <span>Topo: {r.topography_code}</span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
