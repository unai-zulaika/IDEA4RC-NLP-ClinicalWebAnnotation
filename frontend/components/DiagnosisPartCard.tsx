'use client'

import { useEffect, useMemo, useState } from 'react'
import type { StudyVariableReview, CodeSearchResult, CSVRow, InclusionCodeRef } from '@/lib/api'
import { studiesApi } from '@/lib/api'
import CandidateCompareModal from './CandidateCompareModal'

interface Props {
  variable: StudyVariableReview
  part: 'histology' | 'topography'
  family?: string | null
  notesById?: Record<string, CSVRow>
  inclusionCodes?: InclusionCodeRef[]
  inclusionLabel?: string
  busy?: boolean
  onPick: (code: string, label: string) => void
  onReject: () => void
}

/** An inclusion code MATCHES a candidate code by exact match, or by prefix for
 * morphology (the study lists 4-digit prefixes like "8850"; results carry the
 * full "8850/3"). */
function matchesInclusion(code: string, refs: InclusionCodeRef[]): boolean {
  const c = (code || '').trim().toUpperCase()
  return refs.some((r) => {
    const rc = (r.code || '').trim().toUpperCase()
    return rc !== '' && (c === rc || c.startsWith(rc))
  })
}

/**
 * Diagnosis-part card (histology / topography). The LLM's *code* is often
 * hallucinated, so it is not trusted — instead the LLM's *label* is searched
 * against the condition file for real code candidates, which the reviewer picks.
 */
export default function DiagnosisPartCard({
  variable, part, family, notesById = {}, inclusionCodes = [], inclusionLabel, busy, onPick, onReject,
}: Props) {
  const confirmed = variable.status === 'confirmed'
  const rejected = variable.status === 'rejected'

  // Group the inclusion-criteria codes by code (e.g. C49.4 covers several sites)
  // so the reviewer sees a compact "code → sites" reference.
  const inclusionGroups = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const r of inclusionCodes) {
      const arr = m.get(r.code) ?? []
      if (r.label && !arr.includes(r.label)) arr.push(r.label)
      m.set(r.code, arr)
    }
    return Array.from(m, ([code, labels]) => ({ code, labels }))
  }, [inclusionCodes])
  const [showIncl, setShowIncl] = useState(true)

  const [open, setOpen] = useState(!confirmed && !rejected)
  const [query, setQuery] = useState(variable.llm_label || variable.llm_code || '')
  const [results, setResults] = useState<CodeSearchResult[]>([])
  const [selected, setSelected] = useState<string>(variable.selected_code || '')
  const [loading, setLoading] = useState(false)
  const [showNotes, setShowNotes] = useState(false)

  // Auto-search the condition file (debounced) whenever the picker is open.
  useEffect(() => {
    if (!open) return
    const term = query.trim()
    if (!term) { setResults([]); return }
    setLoading(true)
    const timer = setTimeout(async () => {
      try {
        const fn = part === 'histology' ? studiesApi.searchMorphology : studiesApi.searchTopography
        const res = await fn(term, family || undefined, 10)
        setResults(res)
        setSelected((prev) => prev || res[0]?.code || '')
      } catch {
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [query, open, part, family])

  const chosen = results.find((r) => r.code === selected)
  const codeIsFake = variable.llm_code && !results.some((r) => r.code === variable.llm_code)

  // Selecting a note in the compare view seeds the code search with that note's
  // label (stripping any LLM code), so the reviewer can identify the real code.
  const useCandidate = (value: string) => {
    const seed = value
      .replace(/^\s*\d{4}\/\d\s*/, '')
      .replace(/^\s*C\d{2}(\.\d)?\s*/, '')
      .trim() || variable.llm_label || ''
    setShowNotes(false)
    setSelected('')
    setQuery(seed)
    setOpen(true)
  }

  const border = confirmed ? 'border-green-300 dark:border-green-800'
    : rejected ? 'border-red-300 dark:border-red-800'
    : 'border-amber-300 dark:border-amber-800'

  return (
    <div className={`rounded-lg border p-4 ${border} bg-white dark:bg-gray-800`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{variable.label}</h4>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
            {confirmed && <span className="rounded bg-green-100 px-2 py-0.5 font-medium text-green-800 dark:bg-green-900/40 dark:text-green-200">Validated code</span>}
            {rejected && <span className="rounded bg-red-100 px-2 py-0.5 font-medium text-red-700 dark:bg-red-900/40 dark:text-red-200">Invalidated</span>}
            {!confirmed && !rejected && <span className="rounded bg-amber-100 px-2 py-0.5 font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">Pick a real code</span>}
            {variable.reviewed_by && variable.reviewed_by !== 'rule' && <span className="text-gray-400">by {variable.reviewed_by}</span>}
          </div>
        </div>
        {variable.candidates.length > 0 && (
          <button onClick={() => setShowNotes(true)} className="whitespace-nowrap text-xs font-medium text-primary-600 hover:underline dark:text-primary-400">
            {variable.candidates.length > 1 ? 'Compare notes →' : 'View note →'}
          </button>
        )}
      </div>

      {/* LLM's label (trusted) + its code (not trusted) */}
      <div className="mt-3 rounded bg-gray-50 p-2 text-xs dark:bg-gray-900/50">
        <div className="text-gray-700 dark:text-gray-200">
          LLM label: <span className="font-medium">{variable.llm_label || <span className="italic text-gray-400">none extracted</span>}</span>
        </div>
        {variable.llm_code && (
          <div className="mt-0.5 text-gray-500">
            LLM code: <span className={codeIsFake ? 'text-red-500 line-through' : 'font-mono'}>{variable.llm_code}</span>
            {codeIsFake && <span className="ml-1 text-red-500">not in condition file — verify</span>}
          </div>
        )}
      </div>

      {/* inclusion-criteria reference: the codes that qualify a patient for this study */}
      {inclusionGroups.length > 0 && (
        <div className="mt-2 rounded border border-emerald-200 bg-emerald-50/60 p-2 text-xs dark:border-emerald-900 dark:bg-emerald-900/20">
          <button
            type="button"
            onClick={() => setShowIncl((v) => !v)}
            className="flex w-full items-center justify-between gap-2 font-medium text-emerald-800 dark:text-emerald-200"
          >
            <span>✓ Inclusion codes{inclusionLabel ? ` — ${inclusionLabel}` : ''}</span>
            <span className="text-emerald-500">{showIncl ? '▾' : '▸'}</span>
          </button>
          {showIncl && (
            <ul className="mt-1.5 space-y-0.5">
              {inclusionGroups.map((g) => (
                <li key={g.code} className="flex gap-2">
                  <span className="shrink-0 rounded bg-emerald-100 px-1 font-mono font-medium text-emerald-800 dark:bg-emerald-800/50 dark:text-emerald-100">{g.code}</span>
                  <span className="text-gray-700 dark:text-gray-200">{g.labels.join(', ')}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* confirmed summary */}
      {confirmed && !open && (
        <div className="mt-3">
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100">✓ {variable.value}</p>
          <div className="mt-2 flex gap-2">
            <button onClick={() => setOpen(true)} disabled={busy}
              className="rounded border border-gray-300 px-3 py-1 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700">
              Change code
            </button>
            <button onClick={onReject} disabled={busy}
              className="rounded border border-red-300 px-3 py-1 text-sm text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300">
              Reject
            </button>
          </div>
        </div>
      )}

      {/* picker */}
      {open && (
        <div className="mt-3 space-y-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search ${part} by label or code…`}
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
          />
          <div className="max-h-52 space-y-1 overflow-y-auto">
            {loading && <p className="text-xs italic text-gray-400">Searching condition file…</p>}
            {!loading && results.length === 0 && query.trim() && (
              <p className="text-xs italic text-gray-400">No condition-file match for “{query}”.</p>
            )}
            {results.map((r) => {
              const incl = matchesInclusion(r.code, inclusionCodes)
              return (
                <button
                  key={r.code}
                  onClick={() => setSelected(r.code)}
                  className={`flex w-full items-center justify-between gap-2 rounded border px-2 py-1 text-left text-xs ${
                    selected === r.code
                      ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30'
                      : incl
                        ? 'border-emerald-300 bg-emerald-50/60 hover:bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-900/20'
                        : 'border-gray-200 hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-700'
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-primary-700 dark:text-primary-300">{r.code}</span>
                    <span className="text-gray-700 dark:text-gray-100">{r.label}</span>
                    {incl && (
                      <span className="rounded bg-emerald-100 px-1 text-[9px] font-semibold uppercase text-emerald-700 dark:bg-emerald-800/60 dark:text-emerald-200" title="Part of the study inclusion criteria">
                        ✓ incl
                      </span>
                    )}
                  </span>
                  <span className="text-[10px] text-gray-400">{Math.round(r.score * 100)}%</span>
                </button>
              )
            })}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => { if (chosen) { onPick(chosen.code, chosen.label); setOpen(false) } }}
              disabled={busy || !chosen}
              className="rounded bg-green-600 px-3 py-1 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              Use {chosen ? chosen.code : 'selected'} →
            </button>
            {confirmed && (
              <button onClick={() => setOpen(false)} className="rounded border border-gray-300 px-3 py-1 text-sm text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300">
                Cancel
              </button>
            )}
            <button onClick={onReject} disabled={busy}
              className="rounded border border-red-300 px-3 py-1 text-sm text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300">
              {rejected ? 'Rejected' : 'Reject (none correct)'}
            </button>
          </div>
        </div>
      )}

      {showNotes && (
        <CandidateCompareModal
          label={variable.label}
          candidates={variable.candidates}
          notesById={notesById}
          status={variable.status}
          busy={busy}
          pickLabel="Use this note → find its code"
          onPick={useCandidate}
          onReject={() => { setShowNotes(false); onReject() }}
          onClose={() => setShowNotes(false)}
        />
      )}
    </div>
  )
}
