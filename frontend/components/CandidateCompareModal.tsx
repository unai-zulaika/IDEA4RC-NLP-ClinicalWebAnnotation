'use client'

import { useMemo, useState } from 'react'
import type { StudyVariableCandidate, CSVRow, EvidenceSpan } from '@/lib/api'
import TextHighlighter from './TextHighlighter'

/** Parse DD/MM/YYYY to a sortable timestamp; undated sorts last. */
function ts(d?: string | null): number {
  if (!d) return Number.MAX_SAFE_INTEGER
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(d.trim())
  return m ? new Date(+m[3], +m[2] - 1, +m[1]).getTime() : Number.MAX_SAFE_INTEGER
}

interface Props {
  label: string
  candidates: StudyVariableCandidate[]
  notesById: Record<string, CSVRow>
  isDiagnosis?: boolean
  status?: string
  busy?: boolean
  readOnly?: boolean            // view-only (no pick / invalidate) — e.g. an event's source evidence
  pickLabel?: string            // text for the per-candidate select button
  onPick?: (value: string) => void
  onReject?: () => void
  onClose: () => void
}

/**
 * Side-by-side comparison of the candidate values for one study variable: each
 * column shows the value, its source note (evidence highlighted), and the LLM
 * reasoning, so a reviewer can decide which is correct — or invalidate the whole
 * variable when every candidate is wrong. Works for a single candidate too.
 */
export default function CandidateCompareModal({
  label, candidates, notesById, isDiagnosis, status, busy, readOnly, pickLabel, onPick, onReject, onClose,
}: Props) {
  const [showFullNote, setShowFullNote] = useState(true)
  // Always present the notes in chronological order (earliest first).
  const ordered = useMemo(
    () => [...candidates].sort((a, b) => ts(a.date) - ts(b.date)),
    [candidates],
  )
  const single = ordered.length <= 1

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/50 p-4" onClick={onClose}>
      <div
        className="mx-auto flex h-full w-full max-w-[95vw] flex-col overflow-hidden rounded-lg bg-white shadow-xl dark:bg-gray-900"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              {single ? 'Annotation detail' : 'Compare candidates'} · {label}
            </h3>
            <p className="text-xs text-gray-500">
              {single
                ? 'Review the value against its note & reasoning — or invalidate it if it is wrong.'
                : `${ordered.length} values across notes (chronological) — pick the correct one, or invalidate if all are wrong.`}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1 text-xs text-gray-500">
              <input type="checkbox" checked={showFullNote} onChange={(e) => setShowFullNote(e.target.checked)} />
              full note
            </label>
            {!readOnly && onReject && (
              <button
                onClick={onReject}
                disabled={busy}
                title="Mark this variable as having no valid value (none of the annotations is correct)"
                className="rounded border border-red-300 px-2.5 py-1 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-900/30"
              >
                {status === 'rejected' ? 'Invalidated (all wrong)' : 'Invalidate — none correct'}
              </button>
            )}
            <button onClick={onClose} className="rounded px-2 py-1 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800">
              ✕ Close
            </button>
          </div>
        </div>

        {/* columns */}
        <div className="flex flex-1 gap-3 overflow-x-auto p-4">
          {ordered.map((c, i) => {
            const note = notesById[c.note_id]
            const spans = (c.evidence_spans || []) as EvidenceSpan[]
            return (
              <div
                key={`${c.note_id}-${i}`}
                className="flex w-full min-w-[min(24rem,80vw)] flex-col rounded-lg border border-gray-200 dark:border-gray-700 sm:w-[24rem] sm:min-w-[24rem]"
              >
                {/* value + meta */}
                <div className="border-b border-gray-100 p-3 dark:border-gray-700">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{c.value}</span>
                    {c.has_flags && <span title="hallucination / low-confidence flag" className="text-amber-500">⚠</span>}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-400">
                    <span>{c.report_type || 'unknown report'}</span>
                    {c.date && <span>· {c.date}</span>}
                    {c.is_negated && <span className="text-red-500">· negated</span>}
                    <span>· note {c.note_id}</span>
                  </div>
                  {!readOnly && onPick && (
                    <button
                      onClick={() => onPick(c.value)}
                      className="mt-2 w-full rounded bg-green-600 px-3 py-1 text-sm font-medium text-white hover:bg-green-700"
                    >
                      {pickLabel || 'Use this value'}
                    </button>
                  )}
                </div>

                {/* reasoning */}
                <div className="border-b border-gray-100 p-3 dark:border-gray-700">
                  <p className="mb-1 text-xs font-medium text-gray-500">LLM reasoning</p>
                  <p className="max-h-40 overflow-y-auto whitespace-pre-wrap text-xs text-gray-600 dark:text-gray-300">
                    {c.reasoning || <span className="italic text-gray-400">none recorded</span>}
                  </p>
                </div>

                {/* source note */}
                <div className="flex-1 overflow-y-auto p-3">
                  <p className="mb-1 text-xs font-medium text-gray-500">Source note</p>
                  {note?.text ? (
                    showFullNote ? (
                      <div className="text-xs leading-relaxed text-gray-700 dark:text-gray-200">
                        <TextHighlighter text={note.text} spans={spans} selectedPromptType={c.prompt_type} />
                      </div>
                    ) : (
                      <p className="whitespace-pre-wrap text-xs text-gray-600 dark:text-gray-300">
                        {c.annotation_text || note.text.slice(0, 400)}
                      </p>
                    )
                  ) : (
                    <p className="whitespace-pre-wrap text-xs text-gray-500">
                      {c.annotation_text || <span className="italic text-gray-400">note text unavailable</span>}
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
