'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import {
  studiesApi,
  type StudyInfo,
  type StudyReviewReport,
  type StudyPatientReview,
  type StudyEventActionRequest,
  type ConflictConfig,
  type CSVRow,
} from '@/lib/api'
import { sessionsApi } from '@/lib/api'
import { useReviewerName } from '@/lib/useReviewerName'
import ReviewWizard from '@/components/ReviewWizard'
import ConflictSettingsPanel from '@/components/ConflictSettingsPanel'
import EvaluationPanel from '@/components/EvaluationPanel'

const ELIG_BADGE: Record<string, string> = {
  included: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200',
  excluded: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200',
  needs_review: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
}
const OVERALL_DOT: Record<string, string> = {
  completed: 'bg-green-500',
  in_progress: 'bg-amber-500',
  pending: 'bg-gray-300 dark:bg-gray-600',
  excluded: 'bg-red-400',
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default function StudyReviewPage() {
  const params = useParams()
  const sessionId = String(params.sessionId)

  const [reviewer, setReviewer] = useReviewerName()
  const [studies, setStudies] = useState<StudyInfo[]>([])
  const [studyId, setStudyId] = useState<string>('')
  const [report, setReport] = useState<StudyReviewReport | null>(null)
  const [sessionName, setSessionName] = useState('')
  const [notesById, setNotesById] = useState<Record<string, CSVRow>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedPid, setSelectedPid] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'needs_review' | 'included' | 'excluded'>('all')

  // bootstrap: study list + session name
  useEffect(() => {
    studiesApi.list().then((s) => {
      setStudies(s)
      if (s.length) setStudyId((cur) => cur || s[0].id)
    }).catch((e) => setError(String(e?.message || e)))
    sessionsApi.get(sessionId).then((s) => {
      setSessionName(s.name)
      const map: Record<string, CSVRow> = {}
      for (const n of s.notes) map[n.note_id] = n
      setNotesById(map)
    }).catch(() => {})
  }, [sessionId])

  const loadReview = useCallback(async (sid: string) => {
    if (!sid) return
    setLoading(true)
    setError(null)
    try {
      const r = await studiesApi.getReview(sessionId, sid)
      setReport(r)
      setSelectedPid((cur) => cur ?? r.patients[0]?.patient_id ?? null)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to load study review')
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => { if (studyId) loadReview(studyId) }, [studyId, loadReview])

  const patients = report?.patients ?? []
  const counts = useMemo(() => {
    const c = { included: 0, excluded: 0, needs_review: 0, completed: 0 }
    for (const p of patients) {
      c[p.eligibility.decision] = (c[p.eligibility.decision] ?? 0) + 1
      if (p.overall_status === 'completed') c.completed += 1
    }
    return c
  }, [patients])

  const visiblePatients = useMemo(() => {
    const list = filter === 'all' ? patients : patients.filter((p) => p.eligibility.decision === filter)
    const rank = (p: StudyPatientReview) =>
      p.eligibility.decision === 'needs_review' ? 0 :
      p.eligibility.decision === 'included' ? 1 : 2
    return [...list].sort((a, b) => rank(a) - rank(b) || a.patient_id.localeCompare(b.patient_id))
  }, [patients, filter])

  const selected = patients.find((p) => p.patient_id === selectedPid) ?? null
  const [showEval, setShowEval] = useState(false)

  const applyPatient = (p: StudyPatientReview) =>
    setReport((r) => r ? { ...r, patients: r.patients.map((x) => x.patient_id === p.patient_id ? p : x) } : r)

  const confirmVariable = async (pid: string, varKey: string, value: string | null, action: 'confirm' | 'reject') => {
    setBusy(true)
    try {
      const updated = await studiesApi.confirmVariable(sessionId, studyId, pid, varKey, {
        value, action, reviewer: reviewer || undefined,
      })
      applyPatient(updated)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to save')
    } finally {
      setBusy(false)
    }
  }

  const setDiagnosisPart = async (
    pid: string, part: 'histology' | 'topography',
    action: 'select' | 'reject', code?: string, label?: string,
  ) => {
    setBusy(true)
    try {
      const updated = await studiesApi.setDiagnosisPart(sessionId, studyId, pid, {
        part, action, code, label, reviewer: reviewer || undefined,
      })
      applyPatient(updated)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to set diagnosis code')
    } finally {
      setBusy(false)
    }
  }

  const editEvents = async (pid: string, req: StudyEventActionRequest) => {
    setBusy(true)
    try {
      const updated = await studiesApi.editEvents(sessionId, studyId, pid, { ...req, reviewer: reviewer || undefined })
      applyPatient(updated)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to update events')
    } finally {
      setBusy(false)
    }
  }

  const setEligibility = async (pid: string, decision: 'included' | 'excluded') => {
    setBusy(true)
    try {
      const updated = await studiesApi.setEligibility(sessionId, studyId, pid, decision, reviewer || undefined)
      applyPatient(updated)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to set eligibility')
    } finally {
      setBusy(false)
    }
  }

  const saveConflictConfig = async (config: ConflictConfig) => {
    setBusy(true)
    try {
      const r = await studiesApi.setConflictConfig(sessionId, studyId, config)
      setReport(r)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to apply config')
    } finally {
      setBusy(false)
    }
  }

  const exportCohort = async (mode: 'labels' | 'codes') => {
    if (!report) return
    // The export cohort is patients with a CONFIRMED inclusion (auto-proposed
    // 'included' is only a suggestion until a reviewer clicks Include).
    const confirmedIncluded = patients.filter(
      (p) => p.eligibility.decision === 'included' && p.eligibility.confirmed,
    )
    if (confirmedIncluded.length === 0) {
      alert('No patients have a confirmed inclusion yet. Click "Include" on eligible patients to add them to the cohort.')
      return
    }
    const autoOnly = patients.filter(
      (p) => p.eligibility.decision === 'included' && !p.eligibility.confirmed,
    )
    const unvalidated = confirmedIncluded.filter((p) => p.overall_status !== 'completed')
    const warnings: string[] = []
    if (autoOnly.length > 0) {
      warnings.push(`${autoOnly.length} auto-included patient(s) are NOT confirmed and will be skipped.`)
    }
    if (unvalidated.length > 0) {
      warnings.push(`${unvalidated.length} of ${confirmedIncluded.length} included patient(s) are not fully validated; their current (proposed/auto) values will be used.`)
    }
    if (warnings.length > 0 && !confirm(warnings.join('\n\n') + '\n\nExport anyway?')) return
    setBusy(true)
    try {
      const api = mode === 'labels' ? sessionsApi.exportLabels : sessionsApi.exportCodes
      const { blob } = await api(sessionId, { study_id: studyId, force: true })
      const suffix = mode === 'codes' ? '_coded' : ''
      download(blob, `${studyId}_${sessionId}${suffix}.csv`)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Export failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {/* header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/annotate/${sessionId}`} className="text-sm text-primary-600 hover:underline dark:text-primary-400">
            ← Back to annotation
          </Link>
          <h1 className="mt-1 break-words text-xl font-bold text-gray-900 dark:text-gray-100">
            Study review {sessionName && <span className="text-gray-400">· {sessionName}</span>}
          </h1>
        </div>
        <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
          <input
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            placeholder="Your name (reviewer)"
            className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 sm:flex-none"
          />
          {studies.length > 0 && (
            <select
              value={studyId}
              onChange={(e) => { setStudyId(e.target.value); setSelectedPid(null) }}
              className="min-w-0 max-w-full flex-1 truncate rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 sm:flex-none"
            >
              {studies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/30 dark:text-red-200">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-gray-500">Computing study review…</p>
      ) : !report ? (
        <p className="text-sm text-gray-500">No study selected.</p>
      ) : (
        <>
          {/* summary + export */}
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 dark:border-gray-700 dark:bg-gray-800">
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <span className="text-gray-500">{report.total_patients} patients</span>
              <span className="rounded bg-green-100 px-2 py-0.5 text-green-800 dark:bg-green-900/40 dark:text-green-200">{counts.included} included</span>
              <span className="rounded bg-red-100 px-2 py-0.5 text-red-700 dark:bg-red-900/40 dark:text-red-200">{counts.excluded} excluded</span>
              <span className="rounded bg-amber-100 px-2 py-0.5 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">{counts.needs_review} need eligibility</span>
              <span className="text-gray-500">{counts.completed}/{counts.included} included validated</span>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => setShowEval(true)}
                className="rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700"
                title="How often reviewers accept / edit / reject the LLM's proposed values">
                📊 LLM evaluation
              </button>
              <button onClick={() => exportCohort('labels')} disabled={busy}
                className="rounded bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50">
                Export cohort (labels)
              </button>
              <button onClick={() => exportCohort('codes')} disabled={busy}
                className="rounded border border-primary-600 px-3 py-1.5 text-sm font-medium text-primary-700 hover:bg-primary-50 disabled:opacity-50 dark:text-primary-300 dark:hover:bg-primary-900/30">
                Export (codes)
              </button>
            </div>
          </div>

          {showEval && (
            <EvaluationPanel sessionId={sessionId} studyId={studyId} onClose={() => setShowEval(false)} />
          )}

          {/* conflict settings */}
          <div className="mb-4">
            <ConflictSettingsPanel
              reportTypes={report.report_types}
              variables={report.variables.filter((v) => (v.source === 'annotation' || v.source === 'diagnosis') && v.part !== 'combination')}
              config={report.conflict_config}
              busy={busy}
              onSave={saveConflictConfig}
            />
          </div>

          <div className="grid min-w-0 gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
            {/* patient queue */}
            <div className="min-w-0 rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
              <div className="flex flex-wrap gap-1 border-b border-gray-100 p-2 dark:border-gray-700">
                {(['all', 'needs_review', 'included', 'excluded'] as const).map((f) => (
                  <button key={f} onClick={() => setFilter(f)}
                    className={`rounded px-2 py-1 text-xs font-medium ${
                      filter === f ? 'bg-primary-600 text-white' : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700'
                    }`}>
                    {f === 'needs_review' ? 'needs eligibility' : f}
                  </button>
                ))}
              </div>
              <ul className="max-h-[70vh] overflow-y-auto">
                {visiblePatients.map((p) => (
                  <li key={p.patient_id}>
                    <button
                      onClick={() => setSelectedPid(p.patient_id)}
                      className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm ${
                        selectedPid === p.patient_id ? 'bg-primary-50 dark:bg-primary-900/30' : 'hover:bg-gray-50 dark:hover:bg-gray-700'
                      }`}>
                      <span className="flex items-center gap-2">
                        <span className={`inline-block h-2 w-2 rounded-full ${OVERALL_DOT[p.overall_status] ?? 'bg-gray-300'}`} />
                        <span className="font-medium text-gray-800 dark:text-gray-100">{p.patient_id}</span>
                      </span>
                      <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${ELIG_BADGE[p.eligibility.decision]}`}>
                        {p.eligibility.decision === 'needs_review' ? 'review' : p.eligibility.decision}
                      </span>
                    </button>
                  </li>
                ))}
                {visiblePatients.length === 0 && (
                  <li className="px-3 py-4 text-xs italic text-gray-400">No patients in this filter.</li>
                )}
              </ul>
            </div>

            {/* focused patient panel */}
            <div className="min-w-0">
              {!selected ? (
                <p className="text-sm text-gray-500">Select a patient to review.</p>
              ) : (
                <ReviewWizard
                  patient={selected}
                  report={report}
                  notesById={notesById}
                  busy={busy}
                  onConfirmVariable={(varKey, value, action) => confirmVariable(selected.patient_id, varKey, value, action)}
                  onSetDiagnosisPart={(part, action, code, label) => setDiagnosisPart(selected.patient_id, part, action, code, label)}
                  onSetEligibility={(decision) => setEligibility(selected.patient_id, decision)}
                  onEditEvents={(req) => editEvents(selected.patient_id, req)}
                />
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
