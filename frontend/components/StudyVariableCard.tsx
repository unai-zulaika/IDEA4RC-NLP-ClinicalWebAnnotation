'use client'

import { useState } from 'react'
import type { StudyVariableReview, CSVRow } from '@/lib/api'
import CandidateCompareModal from './CandidateCompareModal'

interface Props {
  variable: StudyVariableReview
  notesById?: Record<string, CSVRow>
  busy?: boolean
  locked?: boolean          // e.g. the combination code until its parts are confirmed
  lockReason?: string
  onConfirm: (value: string | null) => void
  onReject: () => void
}

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  auto: { label: 'LLM · unanimous', cls: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200' },
  needs_review: { label: 'Needs review', cls: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200' },
  confirmed: { label: 'Validated', cls: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200' },
  rejected: { label: 'Excluded', cls: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200' },
}

export default function StudyVariableCard({ variable, notesById = {}, busy, locked, lockReason, onConfirm, onReject }: Props) {
  const isDiagnosis = variable.source === 'diagnosis'
  const current = variable.value ?? variable.proposed_value ?? ''
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(current)
  const [showCompare, setShowCompare] = useState(false)

  const badge = STATUS_BADGE[variable.status] ?? STATUS_BADGE.needs_review
  const hasCandidates = variable.candidates.length >= 1

  const startEdit = () => {
    setDraft(variable.value ?? variable.proposed_value ?? '')
    setEditing(true)
  }
  const saveEdit = () => {
    setEditing(false)
    onConfirm(draft.trim() === '' ? null : draft.trim())
  }

  return (
    <div className={`rounded-lg border p-4 ${
      variable.status === 'confirmed'
        ? 'border-green-300 dark:border-green-800'
        : variable.conflict
          ? 'border-amber-300 dark:border-amber-800'
          : 'border-gray-200 dark:border-gray-700'
    } bg-white dark:bg-gray-800`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{variable.label}</h4>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${badge.cls}`}>
              {badge.label}
            </span>
            {variable.auto_resolved && variable.resolution_rule && (
              <span
                className="inline-block rounded px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200"
                title={variable.review_reasons.join(' · ')}
              >
                auto-rule: {variable.resolution_rule}
              </span>
            )}
            {variable.conflict && (
              <span className="inline-block rounded px-2 py-0.5 text-xs font-medium bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
                {variable.candidates.length} conflicting
              </span>
            )}
            {variable.reviewed_by && variable.reviewed_by !== 'rule' && (
              <span className="text-xs text-gray-400">by {variable.reviewed_by}</span>
            )}
          </div>
        </div>
      </div>

      {/* current / confirmed value */}
      <div className="mt-3">
        {editing ? (
          <div className="flex items-center gap-2">
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && saveEdit()}
              className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
            />
            <button onClick={saveEdit} disabled={busy}
              className="rounded bg-primary-600 px-3 py-1 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50">
              Save
            </button>
            <button onClick={() => setEditing(false)} className="text-sm text-gray-500 hover:text-gray-700">
              Cancel
            </button>
          </div>
        ) : (
          <p className="text-sm text-gray-900 dark:text-gray-100">
            {current
              ? <span className="font-medium">{current}</span>
              : <span className="italic text-gray-400">no value extracted</span>}
          </p>
        )}
      </div>

      {/* Notes + reasoning live only in the compare/detail view, so a value is
          never shown next to the wrong note when candidates come from different notes. */}
      {!editing && hasCandidates && (
        <div className="mt-3">
          <button
            onClick={() => setShowCompare(true)}
            className="rounded border border-primary-300 px-3 py-1 text-xs font-medium text-primary-700 hover:bg-primary-50 dark:border-primary-700 dark:text-primary-300 dark:hover:bg-primary-900/30"
          >
            {variable.candidates.length > 1
              ? `Compare ${variable.candidates.length} notes side-by-side →`
              : 'View note & reasoning →'}
          </button>
        </div>
      )}

      {/* actions */}
      {!editing && (
        <>
          {locked && (
            <p className="mt-3 text-xs text-amber-600 dark:text-amber-300">🔒 {lockReason || 'Confirm the required variables first.'}</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {!isDiagnosis && (
              <button onClick={() => onConfirm(current === '' ? null : current)} disabled={busy || current === '' || locked}
                className="rounded bg-green-600 px-3 py-1 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50">
                {variable.status === 'confirmed' ? 'Re-confirm' : 'Confirm'}
              </button>
            )}
            {isDiagnosis && (
              <button onClick={() => onConfirm(current === '' ? null : current)} disabled={busy || current === '' || locked}
                className="rounded bg-green-600 px-3 py-1 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
                title="Acknowledge/validate this diagnosis part. To change the underlying code, use the Diagnosis panel on the annotation page.">
                {variable.status === 'confirmed' ? 'Re-validate' : 'Validate'}
              </button>
            )}
            {!isDiagnosis && (
              <button onClick={startEdit} disabled={busy}
                className="rounded border border-gray-300 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700">
                Edit
              </button>
            )}
            <button onClick={onReject} disabled={busy}
              className="rounded border border-red-300 px-3 py-1 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-900/30">
              {variable.status === 'rejected' ? 'Rejected' : 'Reject'}
            </button>
          </div>
        </>
      )}

      {showCompare && (
        <CandidateCompareModal
          label={variable.label}
          candidates={variable.candidates}
          notesById={notesById}
          isDiagnosis={isDiagnosis}
          status={variable.status}
          busy={busy}
          onPick={(value) => { setShowCompare(false); onConfirm(value) }}
          onReject={() => { setShowCompare(false); onReject() }}
          onClose={() => setShowCompare(false)}
        />
      )}
    </div>
  )
}
