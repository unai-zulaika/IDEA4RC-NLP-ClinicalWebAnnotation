'use client'

import { useCallback, useEffect, useState } from 'react'
import { studiesApi, type StudyEvaluationReport, type StudyEvaluationStat } from '@/lib/api'

/**
 * LLM-vs-human evaluation: how often reviewers ACCEPT / EDIT / REJECT the model's
 * proposed values (a human-in-the-loop quality signal, complementing the offline
 * accuracy / false-positive metrics). accept ~ kept as-is, edit ~ corrected,
 * reject ~ not usable (false positive).
 */

const PCT = (n: number) => `${Math.round(n * 100)}%`

function Bar({ s }: { s: StudyEvaluationStat }) {
  const total = s.reviewed || 1
  const seg = (n: number, cls: string, title: string) =>
    n > 0 ? <div className={cls} style={{ width: `${(n / total) * 100}%` }} title={title} /> : null
  return (
    <div className="flex h-2.5 w-full overflow-hidden rounded bg-gray-100 dark:bg-gray-700">
      {seg(s.accept, 'bg-emerald-500', `${s.accept} accepted`)}
      {seg(s.edit, 'bg-amber-500', `${s.edit} edited`)}
      {seg(s.reject, 'bg-red-500', `${s.reject} rejected`)}
      {seg(s.missed, 'bg-violet-500', `${s.missed} missed (LLM proposed nothing)`)}
    </div>
  )
}

function toCsv(rep: StudyEvaluationReport): string {
  const head = ['variable', 'prompt_type', 'group', 'accept', 'edit', 'reject', 'missed', 'reviewed', 'accept_rate', 'edit_rate', 'reject_rate', 'missed_rate']
  const row = (s: StudyEvaluationStat) => [
    s.label, s.prompt_type ?? '', s.group ?? '', s.accept, s.edit, s.reject, s.missed, s.reviewed,
    s.accept_rate, s.edit_rate, s.reject_rate, s.missed_rate,
  ]
  const esc = (v: unknown) => {
    const t = String(v ?? '')
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t
  }
  return [head, row(rep.overall), ...rep.per_variable.map(row)].map((r) => r.map(esc).join(',')).join('\n')
}

export default function EvaluationPanel({
  sessionId, studyId, onClose,
}: { sessionId: string; studyId: string; onClose: () => void }) {
  const [rep, setRep] = useState<StudyEvaluationReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRep(await studiesApi.getEvaluation(sessionId, studyId))
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to load evaluation')
    } finally {
      setLoading(false)
    }
  }, [sessionId, studyId])

  useEffect(() => { load() }, [load])

  const exportCsv = () => {
    if (!rep) return
    const blob = new Blob([toCsv(rep)], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${studyId}_${sessionId}_llm_evaluation.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const o = rep?.overall

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" onClick={onClose}>
      <div
        className="my-8 w-full max-w-3xl rounded-lg border border-gray-200 bg-white shadow-xl dark:border-gray-700 dark:bg-gray-800"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">LLM evaluation — reviewer decisions</h2>
            <p className="text-xs text-gray-500">How often the human accepts, edits, or rejects the model's proposed value.</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={load} disabled={loading}
              className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700">
              Refresh
            </button>
            <button onClick={exportCsv} disabled={!rep}
              className="rounded bg-primary-600 px-2 py-1 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50">
              Export CSV
            </button>
            <button onClick={onClose} className="rounded px-2 py-1 text-sm text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">✕</button>
          </div>
        </div>

        <div className="p-4">
          {loading ? (
            <p className="text-sm text-gray-500">Computing evaluation…</p>
          ) : error ? (
            <p className="text-sm text-red-600 dark:text-red-300">{error}</p>
          ) : !o || o.reviewed === 0 ? (
            <p className="text-sm text-gray-500">
              No human decisions yet. Accept / edit / reject some variables in the review to populate the evaluation.
            </p>
          ) : (
            <>
              {/* overall */}
              <div className="mb-4 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
                <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm font-medium text-gray-800 dark:text-gray-100">Overall</span>
                  <span className="text-xs text-gray-500">
                    {o.reviewed} decisions · {rep!.reviewed_patients}/{rep!.total_patients} patients reviewed
                  </span>
                </div>
                <Bar s={o} />
                <div className="mt-2 flex flex-wrap gap-4 text-sm">
                  <span className="text-emerald-700 dark:text-emerald-300">✓ Accepted <b>{o.accept}</b> ({PCT(o.accept_rate)})</span>
                  <span className="text-amber-700 dark:text-amber-300">✎ Edited <b>{o.edit}</b> ({PCT(o.edit_rate)})</span>
                  <span className="text-red-700 dark:text-red-300">✕ Rejected <b>{o.reject}</b> ({PCT(o.reject_rate)})</span>
                  <span className="text-violet-700 dark:text-violet-300">＋ Missed <b>{o.missed}</b> ({PCT(o.missed_rate)})</span>
                </div>
              </div>

              {/* per-variable */}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-gray-500">
                    <tr className="border-b border-gray-200 dark:border-gray-700">
                      <th className="py-1.5 pr-2 font-medium">Variable</th>
                      <th className="px-2 font-medium">Distribution</th>
                      <th className="px-2 text-right font-medium text-emerald-600">Accept</th>
                      <th className="px-2 text-right font-medium text-amber-600">Edit</th>
                      <th className="px-2 text-right font-medium text-red-600">Reject</th>
                      <th className="px-2 text-right font-medium text-violet-600">Missed</th>
                      <th className="pl-2 text-right font-medium">n</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rep!.per_variable.map((s) => (
                      <tr key={s.key} className="border-b border-gray-100 dark:border-gray-700/50">
                        <td className="py-1.5 pr-2">
                          <div className="font-medium text-gray-800 dark:text-gray-100">{s.label}</div>
                          {s.prompt_type && <div className="text-[10px] text-gray-400">{s.prompt_type}</div>}
                        </td>
                        <td className="w-40 px-2"><Bar s={s} /></td>
                        <td className="px-2 text-right text-emerald-700 dark:text-emerald-300">{s.accept} <span className="text-gray-400">({PCT(s.accept_rate)})</span></td>
                        <td className="px-2 text-right text-amber-700 dark:text-amber-300">{s.edit}</td>
                        <td className="px-2 text-right text-red-700 dark:text-red-300">{s.reject}</td>
                        <td className="px-2 text-right text-violet-700 dark:text-violet-300">{s.missed}</td>
                        <td className="pl-2 text-right text-gray-500">{s.reviewed}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-[11px] text-gray-400">
                accept = the model's value was kept as-is · edit = a reviewer corrected it · reject = judged not usable
                (a false positive) · missed = the LLM proposed nothing and a reviewer added it (a false negative).
                Rule-auto-resolved and not-yet-reviewed variables are excluded. Outcome events are included as one row.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
