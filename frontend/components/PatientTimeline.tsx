'use client'

import { useState } from 'react'
import type { StudyTimelineEvent, StudyEpisodeEvent, StudyEventActionRequest, CSVRow } from '@/lib/api'
import CandidateCompareModal from './CandidateCompareModal'

/**
 * Interactive clinical timeline. Diagnosis + treatment nodes are read-only
 * (derived from the confirmed variables); the outcome events (recurrence /
 * progression / metastasis) are editable here — the reviewer confirms the
 * assembled list, drops or fixes an event, or adds one the LLM missed.
 * Provenance is visible at a glance: filled ✓ = human-confirmed, dashed = LLM
 * proposed, struck = dropped, ⊕ = manually added, ⚠ = evidence changed on re-run.
 */

const SITE_OPTIONS: { key: string; label: string }[] = [
  { key: 'localised', label: 'Local' },
  { key: 'lung', label: 'Lung' },
  { key: 'metastasisatbone', label: 'Bone' },
  { key: 'liver', label: 'Liver' },
  { key: 'softTissue', label: 'Soft tissue' },
  { key: 'brain', label: 'Brain' },
  { key: 'otherViscera', label: 'Other viscera' },
]
const SITE_LABEL: Record<string, string> = Object.fromEntries(SITE_OPTIONS.map((s) => [s.key, s.label]))

const CAT: Record<string, { solid: string; border: string; text: string; name: string }> = {
  diagnosis:  { solid: 'bg-blue-600',    border: 'border-blue-600',    text: 'text-blue-700 dark:text-blue-300',       name: 'Diagnosis' },
  treatment:  { solid: 'bg-emerald-600', border: 'border-emerald-600', text: 'text-emerald-700 dark:text-emerald-300', name: 'Treatment' },
  recurrence: { solid: 'bg-amber-500',   border: 'border-amber-500',   text: 'text-amber-700 dark:text-amber-300',     name: 'Recurrence' },
  progression:{ solid: 'bg-rose-600',    border: 'border-rose-600',    text: 'text-rose-700 dark:text-rose-300',       name: 'Progression' },
}

function parseDate(d?: string | null): number {
  if (!d) return Number.MAX_SAFE_INTEGER
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(d.trim())
  return m ? new Date(+m[3], +m[2] - 1, +m[1]).getTime() : Number.MAX_SAFE_INTEGER
}

type Node =
  | { kind: 'tl'; date: number; tl: StudyTimelineEvent }
  | { kind: 'ev'; date: number; ev: StudyEpisodeEvent }

interface Props {
  events: StudyEpisodeEvent[]
  timeline: StudyTimelineEvent[]
  notesById?: Record<string, CSVRow>
  busy?: boolean
  onEventAction: (req: StudyEventActionRequest) => void
}

const emptyDraft = { key: '', date: '', disease_status: 'recurrence' as 'recurrence' | 'progression', sites: [] as string[] }

export default function PatientTimeline({ events, timeline, notesById = {}, busy, onEventAction }: Props) {
  const [draft, setDraft] = useState<null | typeof emptyDraft>(null) // open editor (edit or add)
  const [adding, setAdding] = useState(false)
  const [viewing, setViewing] = useState<StudyEpisodeEvent | null>(null) // evidence (note + LLM output)

  // Diagnosis + treatment come from the derived timeline; outcomes come from events.
  const tlNodes: Node[] = (timeline || [])
    .filter((t) => t.category === 'diagnosis' || t.category === 'treatment')
    .map((t) => ({ kind: 'tl' as const, date: parseDate(t.date), tl: t }))
  const evNodes: Node[] = (events || []).map((e) => ({ kind: 'ev' as const, date: parseDate(e.date), ev: e }))
  const nodes = [...tlNodes, ...evNodes].sort(
    (a, b) => (a.kind === 'tl' && a.tl.category === 'diagnosis' ? -1 : b.kind === 'tl' && b.tl.category === 'diagnosis' ? 1 : a.date - b.date),
  )

  const proposedCount = (events || []).filter((e) => e.status === 'proposed').length
  const staleCount = (events || []).filter((e) => e.evidence_changed).length

  const openEdit = (e: StudyEpisodeEvent) => {
    setAdding(false)
    setDraft({ key: e.key, date: e.date || '', disease_status: e.disease_status, sites: [...(e.sites || [])] })
  }
  const openAdd = () => {
    setAdding(true)
    setDraft({ ...emptyDraft })
  }
  const closeDraft = () => { setDraft(null); setAdding(false) }

  const saveDraft = () => {
    if (!draft) return
    onEventAction(adding
      ? { action: 'add', date: draft.date || null, disease_status: draft.disease_status, sites: draft.sites }
      : { action: 'edit', key: draft.key, date: draft.date || null, disease_status: draft.disease_status, sites: draft.sites })
    closeDraft()
  }

  if (nodes.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Clinical timeline</h3>
          <button onClick={openAdd} disabled={busy} className="rounded border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700">+ Add event</button>
        </div>
        No timeline yet.
        {draft && <EventEditor draft={draft} setDraft={setDraft} adding={adding} onSave={saveDraft} onCancel={closeDraft} busy={busy} />}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      {/* header */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Clinical timeline</h3>
        <div className="flex items-center gap-2">
          {staleCount > 0 && (
            <span className="rounded bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-200" title="An event's underlying annotation changed on re-run">
              ⚠ {staleCount} evidence-changed
            </span>
          )}
          <button onClick={openAdd} disabled={busy}
            className="rounded border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700">
            + Add event
          </button>
          <button onClick={() => onEventAction({ action: 'confirm_all' })} disabled={busy || proposedCount === 0}
            className="rounded bg-primary-600 px-2 py-1 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            title="Confirm all proposed outcome events">
            Confirm events{proposedCount ? ` (${proposedCount})` : ''}
          </button>
        </div>
      </div>

      {/* legend */}
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-gray-500 dark:text-gray-400">
        {(['diagnosis', 'treatment', 'recurrence', 'progression'] as const).map((k) => (
          <span key={k} className="inline-flex items-center gap-1"><span className={`inline-block h-2.5 w-2.5 rounded-full ${CAT[k].solid}`} />{CAT[k].name}</span>
        ))}
        <span className="mx-1 h-3 w-px bg-gray-300 dark:bg-gray-600" />
        <span className="inline-flex items-center gap-1"><span className="inline-flex h-2.5 w-2.5 items-center justify-center rounded-full bg-gray-400 text-[7px] text-white">✓</span>confirmed</span>
        <span className="inline-flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-dashed border-gray-400" />LLM proposed</span>
        <span>⊕ added · ⚠ evidence changed · click an outcome event to fix/drop</span>
      </div>

      {/* axis */}
      <div className="overflow-x-auto pb-1">
        <ol className="relative flex min-w-max items-start">
          {nodes.length > 1 && <div className="pointer-events-none absolute h-0.5 bg-gray-200 dark:bg-gray-600" style={{ top: 37, left: 80, right: 80 }} />}
          {nodes.map((n, i) => n.kind === 'tl'
            ? <TimelineNode key={`tl${i}`} t={n.tl} />
            : <EventNode key={`ev${n.ev.key}`} e={n.ev} busy={busy} onEdit={() => openEdit(n.ev)}
                onView={() => setViewing(n.ev)}
                onDrop={() => onEventAction({ action: 'drop', key: n.ev.key })}
                onRestore={() => onEventAction({ action: 'restore', key: n.ev.key })}
                onConfirm={() => onEventAction({ action: 'confirm', key: n.ev.key })} />)}
        </ol>
      </div>

      {draft && <EventEditor draft={draft} setDraft={setDraft} adding={adding} onSave={saveDraft} onCancel={closeDraft} busy={busy} />}

      {/* evidence: the note(s) + LLM output this event came from */}
      {viewing && (
        <CandidateCompareModal
          label={`${viewing.disease_status === 'progression' ? 'Progression' : 'Recurrence'}${viewing.date ? ` · ${viewing.date}` : ''}`}
          candidates={viewing.evidence || []}
          notesById={notesById}
          readOnly
          onClose={() => setViewing(null)}
        />
      )}
    </div>
  )
}

function DateCell({ date, dateFrom }: { date?: string | null; dateFrom: string }) {
  const noDate = !date || dateFrom === 'none'
  const noteDate = dateFrom === 'note' && !noDate
  const approx = dateFrom === 'approx' && !noDate    // diagnosis anchored to the earliest event
  const soft = noteDate || approx
  return (
    <div className={`mb-2 h-5 whitespace-nowrap text-[11px] ${noDate ? 'text-gray-400' : soft ? 'italic text-gray-500 dark:text-gray-400' : 'font-medium text-gray-700 dark:text-gray-300'}`}
      title={approx ? 'Approximate — the diagnosis note date was later than an earlier event, so it is anchored to the earliest event' : noteDate ? 'Date from the note — the LLM did not extract an explicit event date' : undefined}>
      {noDate ? 'undated' : date}
      {approx ? <span className="ml-0.5 align-super text-[8px] not-italic text-gray-400">~approx</span>
        : noteDate && <span className="ml-0.5 align-super text-[8px] not-italic text-gray-400">note</span>}
    </div>
  )
}

function TimelineNode({ t }: { t: StudyTimelineEvent }) {
  const c = CAT[t.category] ?? CAT.recurrence
  return (
    <li className="flex w-40 flex-col items-center px-1">
      <DateCell date={t.date} dateFrom={t.date_from} />
      <span title={t.confirmed ? `Confirmed${t.reviewed_by ? ` by ${t.reviewed_by}` : ''}` : 'LLM-proposed'}
        className={`relative z-10 flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-bold ${t.confirmed ? `${c.solid} text-white` : `border-2 border-dashed bg-white dark:bg-gray-800 ${c.border}`}`}>
        {t.confirmed ? '✓' : ''}
      </span>
      <div className="mt-2 text-center">
        <div className={`text-xs font-semibold ${c.text}`}>{t.label}</div>
        {t.detail && <div className="mt-0.5 break-words text-[11px] text-gray-500 dark:text-gray-400">{t.detail}</div>}
      </div>
    </li>
  )
}

function EventNode({ e, busy, onEdit, onView, onDrop, onRestore, onConfirm }: {
  e: StudyEpisodeEvent; busy?: boolean; onEdit: () => void; onView: () => void; onDrop: () => void; onRestore: () => void; onConfirm: () => void
}) {
  const c = CAT[e.disease_status] ?? CAT.recurrence
  const dropped = e.status === 'dropped'
  const confirmed = e.status === 'confirmed'
  const sites = (e.sites || []).map((s) => SITE_LABEL[s] || s).join(', ')
  const node = dropped
    ? 'border-2 border-gray-300 bg-gray-100 text-gray-400 line-through dark:border-gray-600 dark:bg-gray-700'
    : confirmed ? `${c.solid} text-white` : `border-2 border-dashed bg-white dark:bg-gray-800 ${c.border}`
  return (
    <li className="flex w-40 flex-col items-center px-1">
      <DateCell date={e.date} dateFrom={e.date_from} />
      <button onClick={onEdit} disabled={busy}
        title={dropped ? 'Dropped — click to edit/restore' : confirmed ? `Confirmed${e.reviewed_by ? ` by ${e.reviewed_by}` : ''}` : 'LLM-proposed — click to edit'}
        className={`relative z-10 flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-bold ${node} ${e.evidence_changed ? 'ring-2 ring-amber-400 ring-offset-1 dark:ring-offset-gray-800' : ''}`}>
        {e.origin === 'manual' ? '⊕' : confirmed ? '✓' : ''}
      </button>
      <div className="mt-2 text-center">
        <div className={`text-xs font-semibold ${dropped ? 'text-gray-400 line-through' : c.text}`}>
          {e.disease_status === 'progression' ? 'Progression' : 'Recurrence'}
        </div>
        {sites && <div className="mt-0.5 break-words text-[11px] text-gray-500 dark:text-gray-400">{sites}</div>}
        <div className="mt-0.5 flex flex-wrap justify-center gap-1 text-[9px]">
          {e.before_diagnosis && <span className="font-medium text-red-600" title="This event's date is BEFORE the diagnosis — an event cannot precede diagnosis, so the date is likely wrong (a historical mention or over-derived). Verify or fix it.">⚠ before diagnosis</span>}
          {e.evidence_changed && <span className="text-amber-600" title="Underlying annotation changed on re-run">⚠ evidence</span>}
          {e.origin === 'manual' && <span className="text-gray-400">added</span>}
          {e.edited && <span className="text-gray-400">edited</span>}
          {e.status === 'proposed' && <span className="font-medium uppercase tracking-wide text-gray-400">LLM</span>}
        </div>
        {/* quick actions */}
        <div className="mt-1 flex flex-wrap justify-center gap-1">
          {!dropped && !confirmed && <button onClick={onConfirm} disabled={busy} className="rounded border border-emerald-300 px-1 text-[9px] text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 dark:border-emerald-800 dark:text-emerald-300">confirm</button>}
          {(e.evidence || []).length > 0 && <button onClick={onView} className="rounded border border-gray-300 px-1 text-[9px] text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300" title="See the note(s) + LLM output this event came from">📄 source</button>}
          {dropped
            ? <button onClick={onRestore} disabled={busy} className="rounded border border-gray-300 px-1 text-[9px] text-gray-600 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-300">restore</button>
            : <button onClick={onDrop} disabled={busy} className="rounded border border-red-300 px-1 text-[9px] text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300">drop</button>}
        </div>
      </div>
    </li>
  )
}

function EventEditor({ draft, setDraft, adding, onSave, onCancel, busy }: {
  draft: typeof emptyDraft; setDraft: (d: typeof emptyDraft) => void; adding: boolean
  onSave: () => void; onCancel: () => void; busy?: boolean
}) {
  const toggleSite = (k: string) =>
    setDraft({ ...draft, sites: draft.sites.includes(k) ? draft.sites.filter((s) => s !== k) : [...draft.sites, k] })
  return (
    <div className="mt-3 rounded-lg border border-primary-200 bg-primary-50/50 p-3 dark:border-primary-800 dark:bg-primary-900/20">
      <div className="mb-2 text-xs font-semibold text-gray-800 dark:text-gray-100">{adding ? 'Add outcome event (LLM miss)' : 'Edit outcome event'}</div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-gray-600 dark:text-gray-300">
          <div className="mb-0.5">Date (DD/MM/YYYY)</div>
          <input value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} placeholder="12/05/2021"
            className="w-32 rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100" />
        </label>
        <label className="text-xs text-gray-600 dark:text-gray-300">
          <div className="mb-0.5">Status</div>
          <select value={draft.disease_status} onChange={(e) => setDraft({ ...draft, disease_status: e.target.value as 'recurrence' | 'progression' })}
            className="rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100">
            <option value="recurrence">Recurrence</option>
            <option value="progression">Progression</option>
          </select>
        </label>
      </div>
      <div className="mt-2 text-xs text-gray-600 dark:text-gray-300">
        <div className="mb-1">Metastatic site(s)</div>
        <div className="flex flex-wrap gap-2">
          {SITE_OPTIONS.map((s) => (
            <label key={s.key} className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${draft.sites.includes(s.key) ? 'border-rose-400 bg-rose-50 text-rose-700 dark:border-rose-700 dark:bg-rose-900/30 dark:text-rose-200' : 'border-gray-300 text-gray-600 dark:border-gray-600 dark:text-gray-300'}`}>
              <input type="checkbox" className="sr-only" checked={draft.sites.includes(s.key)} onChange={() => toggleSite(s.key)} />
              {s.label}
            </label>
          ))}
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <button onClick={onSave} disabled={busy} className="rounded bg-primary-600 px-3 py-1 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50">
          {adding ? 'Add event' : 'Save'}
        </button>
        <button onClick={onCancel} className="rounded border border-gray-300 px-3 py-1 text-sm text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700">Cancel</button>
      </div>
    </div>
  )
}
