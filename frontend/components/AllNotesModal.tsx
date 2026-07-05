'use client'

import { useState } from 'react'
import type { CSVRow } from '@/lib/api'

interface Props {
  patientId: string
  notes: CSVRow[]
  onClose: () => void
}

/**
 * Full scrollable view of every note belonging to one patient, so a reviewer can
 * read the source material manually — e.g. to find a variable the LLM missed and
 * then enter it by hand on the variable card.
 */
export default function AllNotesModal({ patientId, notes, onClose }: Props) {
  const [query, setQuery] = useState('')

  const q = query.trim().toLowerCase()
  const shown = q
    ? notes.filter((n) =>
        (n.text || '').toLowerCase().includes(q) ||
        (n.report_type || '').toLowerCase().includes(q))
    : notes

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/50 p-4" onClick={onClose}>
      <div
        className="mx-auto flex h-full w-full max-w-3xl flex-col overflow-hidden rounded-lg bg-white shadow-xl dark:bg-gray-900"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-center justify-between gap-3 border-b border-gray-200 px-4 py-3 dark:border-gray-700">
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              All notes · Patient {patientId}
            </h3>
            <p className="text-xs text-gray-500">
              {notes.length} note{notes.length === 1 ? '' : 's'} — scroll to read the source material.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find in notes…"
              className="rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
            />
            <button onClick={onClose} className="rounded px-2 py-1 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800">
              ✕ Close
            </button>
          </div>
        </div>

        {/* scrollable list of notes */}
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {shown.length === 0 ? (
            <p className="text-sm italic text-gray-400">No notes match “{query}”.</p>
          ) : (
            shown.map((n, i) => (
              <div key={`${n.note_id}-${i}`} className="rounded-lg border border-gray-200 dark:border-gray-700">
                <div className="flex flex-wrap items-center gap-2 border-b border-gray-100 px-3 py-2 text-xs text-gray-500 dark:border-gray-700">
                  <span className="rounded bg-gray-100 px-2 py-0.5 font-medium text-gray-700 dark:bg-gray-700 dark:text-gray-200">
                    {n.report_type || 'unknown report'}
                  </span>
                  {n.date && <span>· {n.date}</span>}
                  <span className="truncate text-gray-400">· {n.note_id}</span>
                </div>
                <p className="whitespace-pre-wrap px-3 py-2 text-xs leading-relaxed text-gray-700 dark:text-gray-200">
                  {n.text || <span className="italic text-gray-400">empty note</span>}
                </p>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
