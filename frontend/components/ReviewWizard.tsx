'use client'

import { useEffect, useMemo, useState } from 'react'
import type { StudyPatientReview, StudyReviewReport, StudyVariableDef, CSVRow, StudyEventActionRequest } from '@/lib/api'
import StudyVariableCard from './StudyVariableCard'
import DiagnosisPartCard from './DiagnosisPartCard'
import PatientTimeline from './PatientTimeline'
import AllNotesModal from './AllNotesModal'

const ELIG_BADGE: Record<string, string> = {
  included: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200',
  excluded: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200',
  needs_review: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
}

type StepKey = 'diagnosis' | 'baseline' | 'course' | 'outcome'
const STEPS: { key: StepKey; title: string; hint: string }[] = [
  { key: 'diagnosis', title: 'Diagnosis & eligibility', hint: 'Identify the tumour, then decide in or out of the study.' },
  { key: 'baseline', title: 'At diagnosis', hint: 'The tumour and the first treatments, at the start.' },
  { key: 'course', title: 'Disease course', hint: 'Recurrences and progressions over time, and the treatments for each.' },
  { key: 'outcome', title: 'Outcome & finish', hint: 'Final status, then a last check before you move on.' },
]

/** Which step a variable belongs to: diagnosis parts -> step 1; Outcome-group
 *  (non-event) -> step 4; everything else describes the baseline (step 2). */
function stepOf(v: StudyVariableDef): StepKey {
  if (v.part === 'histology' || v.part === 'topography' || v.part === 'combination') return 'diagnosis'
  if ((v.group || '') === 'Outcome') return 'outcome'
  return 'baseline'
}

const SUBGROUPS = ['Clinical', 'Diagnosis', 'Pathology', 'Treatment', 'Other']

interface Props {
  patient: StudyPatientReview
  report: StudyReviewReport
  notesById: Record<string, CSVRow>
  busy?: boolean
  onConfirmVariable: (varKey: string, value: string | null, action: 'confirm' | 'reject') => void
  onSetDiagnosisPart: (part: 'histology' | 'topography', action: 'select' | 'reject', code?: string, label?: string) => void
  onSetEligibility: (decision: 'included' | 'excluded') => void
  onEditEvents: (req: StudyEventActionRequest) => void
}

export default function ReviewWizard({
  patient, report, notesById, busy,
  onConfirmVariable, onSetDiagnosisPart, onSetEligibility, onEditEvents,
}: Props) {
  const [step, setStep] = useState<StepKey>('diagnosis')
  const [showAllNotes, setShowAllNotes] = useState(false)
  useEffect(() => { setStep('diagnosis') }, [patient.patient_id])   // start each patient at step 1

  const patientNotes = useMemo(
    () => Object.values(notesById).filter((n) => n.p_id === patient.patient_id),
    [notesById, patient.patient_id],
  )
  // Cards only — event_any variables (recurrence/metastasis) live on the timeline.
  const cardVars = useMemo(() => report.variables.filter((v) => v.source !== 'event_any'), [report.variables])

  // A treatment the timeline places AFTER a relapse belongs to that disease phase,
  // so it is reviewed in step 3 (Disease course), NOT in step 2 (At diagnosis).
  const parseDate = (d?: string | null) => {
    const m = d && /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(d.trim())
    return m ? new Date(+m[3], +m[2] - 1, +m[1]).getTime() : NaN
  }
  const postRelapseVarKeys = useMemo(() => {
    const s = new Set<string>()
    for (const t of patient.timeline || [])
      if (t.category === 'treatment' && t.variable_key && /\(post-relapse\)/i.test(t.label)) s.add(t.variable_key)
    return s
  }, [patient.timeline])

  // Group each post-relapse treatment under the relapse (recurrence/progression) it follows.
  const phaseGroups = useMemo(() => {
    const relapses = (patient.events || [])
      .filter((e) => e.status !== 'dropped' && e.date && !e.before_diagnosis)
      .map((e) => ({ e, ts: parseDate(e.date) }))
      .filter((r) => !Number.isNaN(r.ts))
      .sort((a, b) => a.ts - b.ts)
    const treats = (patient.timeline || [])
      .filter((t) => t.category === 'treatment' && t.variable_key && postRelapseVarKeys.has(t.variable_key) && t.date)
      .map((t) => ({ key: t.variable_key as string, ts: parseDate(t.date) }))
    const groups = relapses.map((r) => ({ ev: r.e, keys: [] as string[] }))
    const orphan: string[] = []
    for (const t of treats) {
      let idx = -1
      relapses.forEach((r, i) => { if (r.ts <= t.ts) idx = i })
      if (idx >= 0) groups[idx].keys.push(t.key)
      else orphan.push(t.key)
    }
    return { groups: groups.filter((g) => g.keys.length > 0), orphan }
  }, [patient.events, patient.timeline, postRelapseVarKeys])

  const varsForStep = (k: StepKey) => cardVars.filter((v) => {
    if (postRelapseVarKeys.has(v.key)) return k === 'course'   // reviewed with its phase in step 3
    return stepOf(v) === k
  })
  const cardByKey = (key: string) => cardVars.find((v) => v.key === key)

  const varDone = (key: string) => {
    const s = patient.variables[key]?.status
    return s === 'confirmed' || s === 'rejected'
  }

  // progress per step -> {ok, total}
  const progress = (k: StepKey): { ok: number; total: number } => {
    if (k === 'course') {
      const evs = patient.events || []
      const proposed = evs.filter((e) => e.status === 'proposed').length
      const cc = varsForStep('course')                 // post-relapse treatment cards
      const ccDone = cc.filter((v) => varDone(v.key)).length
      return { ok: (evs.length - proposed) + ccDone, total: evs.length + cc.length }
    }
    const vs = varsForStep(k)
    let ok = vs.filter((v) => varDone(v.key)).length
    let total = vs.length
    if (k === 'diagnosis') { total += 1; if (patient.eligibility.confirmed) ok += 1 } // + the include/exclude decision
    return { ok, total }
  }
  const stepDone = (k: StepKey) => { const p = progress(k); return p.total > 0 && p.ok >= p.total }

  const renderCard = (vdef: StudyVariableDef, stripDx = false) => {
    const vr0 = patient.variables[vdef.key]
    if (!vr0) return null
    // under a relapse phase, the variable's "... at diagnosis" name is misleading
    const vr = stripDx && vr0.label ? { ...vr0, label: vr0.label.replace(/\s+at diagnosis$/i, '') } : vr0
    if (vdef.part === 'histology' || vdef.part === 'topography') {
      const part = vdef.part
      const incl = report.inclusion_criteria
      return (
        <DiagnosisPartCard
          key={`${patient.patient_id}:${vdef.key}`}
          variable={vr} part={part} family={report.condition_family} notesById={notesById}
          inclusionCodes={part === 'histology' ? incl?.histology : incl?.topography}
          inclusionLabel={part === 'histology' ? incl?.histology_label : incl?.topography_label}
          busy={busy}
          onPick={(code, label) => onSetDiagnosisPart(part, 'select', code, label)}
          onReject={() => onSetDiagnosisPart(part, 'reject')}
        />
      )
    }
    const requires = vdef.requires || []
    const missing = requires.filter((k) => patient.variables[k]?.status !== 'confirmed')
    const locked = missing.length > 0
    const lockReason = locked
      ? `Confirm ${missing.map((k) => report.variables.find((v) => v.key === k)?.label || k).join(' & ')} first`
      : undefined
    return (
      <StudyVariableCard
        key={`${patient.patient_id}:${vdef.key}`}
        variable={vr} notesById={notesById} busy={busy} locked={locked} lockReason={lockReason}
        onConfirm={(value) => onConfirmVariable(vdef.key, value, 'confirm')}
        onReject={() => onConfirmVariable(vdef.key, null, 'reject')}
      />
    )
  }

  const cardGrid = (vars: StudyVariableDef[], stripDx = false) => (
    <div className="grid min-w-0 gap-3 md:grid-cols-2 [&>*]:min-w-0">{vars.map((v) => renderCard(v, stripDx))}</div>
  )

  const idx = STEPS.findIndex((s) => s.key === step)
  const cur = STEPS[idx]

  return (
    <div className="min-w-0 space-y-4">
      {/* persistent patient header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">Patient {patient.patient_id}</h2>
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${ELIG_BADGE[patient.eligibility.decision]}`}>
            {patient.eligibility.decision}{patient.eligibility.confirmed ? ' ✓' : ' (auto)'}
          </span>
        </div>
        {patientNotes.length > 0 && (
          <button onClick={() => setShowAllNotes(true)}
            className="rounded border border-gray-300 px-2 py-0.5 text-xs font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
            title="Read every note for this patient">
            📄 View all {patientNotes.length} notes
          </button>
        )}
      </div>

      {/* stepper */}
      <ol className="flex min-w-0 gap-2 overflow-x-auto pb-1">
        {STEPS.map((s, i) => {
          const active = s.key === step
          const done = stepDone(s.key)
          const p = progress(s.key)
          return (
            <li key={s.key} className="min-w-0 flex-1">
              <button onClick={() => setStep(s.key)}
                className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left ${
                  active ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/30'
                    : 'border-gray-200 bg-white hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:hover:bg-gray-700'
                }`}>
                <span className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                  done ? 'bg-green-600 text-white'
                    : active ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-600 dark:bg-gray-600 dark:text-gray-200'
                }`}>{done ? '✓' : i + 1}</span>
                <span className="min-w-0">
                  <span className={`block truncate text-xs font-semibold ${active ? 'text-primary-700 dark:text-primary-200' : 'text-gray-700 dark:text-gray-200'}`}>{s.title}</span>
                  <span className="block text-[10px] text-gray-400">{p.total ? `${p.ok}/${p.total} done` : '—'}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>

      {/* current step */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-3">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Step {idx + 1} · {cur.title}</h3>
          <p className="mt-0.5 text-xs text-gray-500">{cur.hint}</p>
        </div>

        {step === 'diagnosis' && (
          <div className="space-y-4">
            {/* eligibility decision */}
            <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-700">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-gray-800 dark:text-gray-100">Is this patient in the study?</span>
                <div className="flex items-center gap-2">
                  <button onClick={() => onSetEligibility('included')} disabled={busy}
                    className="rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50">Include</button>
                  <button onClick={() => onSetEligibility('excluded')} disabled={busy}
                    className="rounded border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-900/30">Exclude</button>
                </div>
              </div>
              {patient.eligibility.reasons.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-xs text-gray-600 dark:text-gray-300">
                  {patient.eligibility.reasons.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              )}
            </div>
            {cardGrid(varsForStep('diagnosis'))}
          </div>
        )}

        {step === 'baseline' && (
          <div className="space-y-4">
            {SUBGROUPS.map((g) => {
              const vs = varsForStep('baseline').filter((v) => (v.group || 'Other') === g)
              if (vs.length === 0) return null
              return (
                <div key={g}>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">{g}</h4>
                  {cardGrid(vs)}
                </div>
              )
            })}
          </div>
        )}

        {step === 'course' && (
          <div className="space-y-4">
            <p className="text-xs text-gray-500">Each recurrence or progression is a phase of the disease. Confirm the list, drop anything wrong, fix a date or its sites, or add one the AI missed. Treatments given after a relapse are reviewed with their phase below.</p>
            <PatientTimeline
              events={patient.events} timeline={patient.timeline} notesById={notesById}
              busy={busy} onEventAction={onEditEvents}
            />
            {phaseGroups.groups.map((g, i) => (
              <div key={`ph${i}`} className="rounded-lg border border-gray-200 p-3 dark:border-gray-700">
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                  Treatments after the {g.ev.disease_status}{g.ev.date ? ` on ${g.ev.date}` : ''}
                </h4>
                {cardGrid(g.keys.map(cardByKey).filter(Boolean) as StudyVariableDef[], true)}
              </div>
            ))}
            {phaseGroups.orphan.length > 0 && (
              <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-700">
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">Treatments after a relapse</h4>
                {cardGrid(phaseGroups.orphan.map(cardByKey).filter(Boolean) as StudyVariableDef[], true)}
              </div>
            )}
          </div>
        )}

        {step === 'outcome' && (
          <div className="space-y-4">
            {varsForStep('outcome').length > 0
              ? cardGrid(varsForStep('outcome'))
              : <p className="text-xs italic text-gray-400">No outcome variables to confirm for this study.</p>}
            <FinishSummary patient={patient} cardVars={cardVars} varDone={varDone} />
          </div>
        )}
      </div>

      {/* back / next */}
      <div className="flex items-center justify-between gap-2">
        <button onClick={() => setStep(STEPS[Math.max(0, idx - 1)].key)} disabled={idx === 0}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-40 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700">
          ← Back
        </button>
        {idx < STEPS.length - 1 ? (
          <button onClick={() => setStep(STEPS[idx + 1].key)}
            className="rounded bg-primary-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-700">
            Next: {STEPS[idx + 1].title} →
          </button>
        ) : (
          <span className="text-xs text-gray-400">Last step — pick the next patient on the left when you're done.</span>
        )}
      </div>

      {showAllNotes && (
        <AllNotesModal patientId={patient.patient_id} notes={patientNotes} onClose={() => setShowAllNotes(false)} />
      )}
    </div>
  )
}

function FinishSummary({ patient, cardVars, varDone }: {
  patient: StudyPatientReview
  cardVars: StudyVariableDef[]
  varDone: (key: string) => boolean
}) {
  const pending = cardVars.filter((v) => !varDone(v.key))
  const eventsProposed = (patient.events || []).filter((e) => e.status === 'proposed').length
  const allDone = pending.length === 0 && eventsProposed === 0 && patient.eligibility.confirmed
  return (
    <div className={`rounded-lg border p-3 text-sm ${allDone
      ? 'border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-900/20'
      : 'border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/20'}`}>
      <div className="font-medium text-gray-800 dark:text-gray-100">
        {allDone ? '✓ This patient is complete.' : 'Almost there — a few things still need a decision:'}
      </div>
      {!allDone && (
        <ul className="mt-1.5 space-y-0.5 text-xs text-gray-600 dark:text-gray-300">
          {!patient.eligibility.confirmed && <li>• Confirm <strong>Include</strong> or <strong>Exclude</strong> (Step 1).</li>}
          {eventsProposed > 0 && <li>• {eventsProposed} timeline event(s) not yet confirmed (Step 3).</li>}
          {pending.slice(0, 6).map((v) => <li key={v.key}>• <strong>{v.label}</strong> still needs Confirm / Edit / Reject.</li>)}
          {pending.length > 6 && <li>• …and {pending.length - 6} more.</li>}
        </ul>
      )}
    </div>
  )
}
