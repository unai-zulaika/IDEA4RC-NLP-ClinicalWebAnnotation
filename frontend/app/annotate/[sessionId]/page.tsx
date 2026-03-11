'use client'

import { useState, useEffect, useRef, useCallback, startTransition } from 'react'
import { useParams } from 'next/navigation'
import { sessionsApi, annotateApi, promptsApi, presetsApi } from '@/lib/api'
import { useDefaultCenter } from '@/lib/useDefaultCenter'
import { useFastMode } from '@/lib/useFastMode'
import type { SessionData, AnnotationResult, EvidenceSpan, PromptInfo, BatchProcessResponse, DiagnosisValidationReport, SequentialProgressEvent, ExportConflict } from '@/lib/api'
import ManagePromptTypesModal from '@/components/ManagePromptTypesModal'
import PatientDiagnosisPanel from '@/components/PatientDiagnosisPanel'
import TextHighlighter from '@/components/TextHighlighter'
import AnnotationViewer from '@/components/AnnotationViewer'
import { extractExpectedAnnotation } from '@/lib/annotationUtils'

function formatTimeRemaining(seconds: number): string {
  if (seconds < 60) {
    return `${seconds} seconds`
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${minutes}m ${secs}s`
  } else {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${hours}h ${minutes}m`
  }
}

export default function AnnotatePage() {
  const params = useParams()
  const sessionId = params.sessionId as string
  const [center] = useDefaultCenter()
  const [fastMode, setFastMode] = useFastMode()

  const [session, setSession] = useState<SessionData | null>(null)
  const [selectedNoteIndex, setSelectedNoteIndex] = useState(0)
  const [selectedPromptType, setSelectedPromptType] = useState<string | null>(null)
  const [processing, setProcessing] = useState(false)
  const [processingAll, setProcessingAll] = useState(false)
  const [noteProgress, setNoteProgress] = useState({
    current: 0,
    total: 0,
    currentPrompt: '',
    percentage: 0,
  })
  const [progress, setProgress] = useState({
    current: 0,
    total: 0,
    currentNote: '',
    percentage: 0,
    timeRemaining: 0, // seconds
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showPromptTypesModal, setShowPromptTypesModal] = useState(false)
  const [availablePrompts, setAvailablePrompts] = useState<PromptInfo[]>([])
  const [exporting, setExporting] = useState<'labels' | 'codes' | 'session' | null>(null)
  const [exclusionReport, setExclusionReport] = useState<import('@/lib/api').ExcludedRow[] | null>(null)
  const [showDiagnosisPanel, setShowDiagnosisPanel] = useState(false)
  const [scrollToPromptType, setScrollToPromptType] = useState<string | null>(null)
  const [diagnosisValidation, setDiagnosisValidation] = useState<{
    mode: 'labels' | 'codes'
    report: DiagnosisValidationReport
  } | null>(null)
  const [exportConflicts, setExportConflicts] = useState<ExportConflict[] | null>(null)
  const [reprocessConfirm, setReprocessConfirm] = useState(false)
  // AbortController for cancelling in-flight requests
  const abortControllerRef = useRef<AbortController | null>(null)
  // Last batch timing breakdown
  const [lastTimingBreakdown, setLastTimingBreakdown] = useState<Record<string, number> | null>(null)
  // Track which single prompt is being processed (null = none)
  const [processingSinglePrompt, setProcessingSinglePrompt] = useState<string | null>(null)
  // Elapsed time tracking for batch processing
  const [elapsedTime, setElapsedTime] = useState(0)
  // Timing report after batch completion
  const [batchTimingReport, setBatchTimingReport] = useState<{
    totalTime: number
    processed: number
    skipped: number
    errors: number
    avgPerNote: number
    minPerNote: number
    maxPerNote: number
  } | null>(null)

  // Elapsed time counter — uses requestAnimationFrame for resilience to main-thread blocking
  const elapsedStartRef = useRef<number>(0)
  const rafIdRef = useRef<number>(0)
  const lastElapsedSecRef = useRef<number>(-1)
  useEffect(() => {
    if (processingAll) {
      setElapsedTime(0)
      elapsedStartRef.current = Date.now()
      lastElapsedSecRef.current = -1
      const tick = () => {
        const sec = Math.round((Date.now() - elapsedStartRef.current) / 1000)
        if (sec !== lastElapsedSecRef.current) {
          lastElapsedSecRef.current = sec
          setElapsedTime(sec)
        }
        rafIdRef.current = requestAnimationFrame(tick)
      }
      rafIdRef.current = requestAnimationFrame(tick)
    } else {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current)
        rafIdRef.current = 0
      }
    }
    return () => {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current)
        rafIdRef.current = 0
      }
    }
  }, [processingAll])

  useEffect(() => {
    loadSession()
  }, [sessionId])

  useEffect(() => {
    loadAvailablePrompts()
  }, [center])

  // Scroll to a specific annotation after navigating from the diagnosis panel
  useEffect(() => {
    if (!scrollToPromptType) return
    // Use a short delay to allow React to render the new note's annotations
    const timer = setTimeout(() => {
      const el = document.getElementById(`annotation-${scrollToPromptType}`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        el.classList.add('ring-2', 'ring-purple-400', 'ring-offset-2')
        setTimeout(() => el.classList.remove('ring-2', 'ring-purple-400', 'ring-offset-2'), 2000)
      }
      setScrollToPromptType(null)
    }, 100)
    return () => clearTimeout(timer)
  }, [scrollToPromptType, selectedNoteIndex])

  const navigateToAnnotation = useCallback((noteId: string, promptType: string) => {
    if (!session) return
    const noteIndex = session.notes.findIndex(n => n.note_id === noteId)
    if (noteIndex === -1) return
    setSelectedNoteIndex(noteIndex)
    setScrollToPromptType(promptType)
  }, [session])

  const loadAvailablePrompts = async () => {
    try {
      const prompts = await promptsApi.list(center)
      setAvailablePrompts(prompts)
    } catch (err) {
      console.error('Failed to load prompts:', err)
    }
  }

  const loadSession = async () => {
    try {
      const data = await sessionsApi.get(sessionId)
      setSession(data)
    } catch (err: any) {
      setError(err.message || 'Failed to load session')
    } finally {
      setLoading(false)
    }
  }

  // Get the prompt types applicable to a specific note based on report_type_mapping + overrides - exclusions
  const getPromptTypesForNote = (note: { note_id?: string; report_type?: string }): string[] => {
    if (!session) return []
    const mapping = session.report_type_mapping
    const noteId = note.note_id || ''
    let prompts: string[] = []
    if (mapping && note.report_type && mapping[note.report_type]) {
      prompts = [...mapping[note.report_type]]
    }
    // Remove per-note exclusions (prompts removed from this specific note)
    const exclusions = session.note_prompt_exclusions?.[noteId] || []
    if (exclusions.length > 0) {
      prompts = prompts.filter(pt => !exclusions.includes(pt))
    }
    // Merge per-note overrides (prompts added specifically to this note)
    const overrides = session.note_prompt_overrides?.[noteId] || []
    for (const pt of overrides) {
      if (!prompts.includes(pt)) {
        prompts.push(pt)
      }
    }
    return prompts
  }

  const handleCancelProcessing = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
  }, [])

  const handleProcessNote = async () => {
    if (!session) return

    const note = session.notes[selectedNoteIndex]
    if (!note) return

    const notePromptTypes = getPromptTypesForNote(note)
    const totalPrompts = notePromptTypes.length

    setProcessing(true)
    setError(null)
    setLastTimingBreakdown(null)
    const controller = new AbortController()
    abortControllerRef.current = controller

    setNoteProgress({
      current: 0,
      total: totalPrompts,
      currentPrompt: `Processing ${totalPrompts} prompts...`,
      percentage: 10,
    })

    try {
      const updatedAnnotations = { ...session.annotations }
      if (!updatedAnnotations[note.note_id]) {
        updatedAnnotations[note.note_id] = {}
      }

      // Send ALL prompts in a single batch call (processed in parallel on backend)
      // Use SSE streaming to avoid reverse-proxy idle timeouts, with fallback
      const batchRequest = {
        note_ids: [note.note_id],
        prompt_types: notePromptTypes,
        fewshot_k: 5,
        use_fewshots: !fastMode,
        fast_mode: fastMode,
      }
      let result: BatchProcessResponse
      try {
        result = await annotateApi.batchProcessStream(
          sessionId,
          batchRequest,
          (prog) => {
            setNoteProgress({
              current: prog.completed,
              total: prog.total,
              currentPrompt: `Processing ${prog.prompt_type} (${prog.completed}/${prog.total})`,
              percentage: prog.percentage,
            })
          },
          controller.signal,
        )
      } catch (streamErr: any) {
        if (streamErr.name === 'AbortError' || streamErr.code === 'ERR_CANCELED') throw streamErr
        console.warn('SSE streaming failed, falling back to standard batch:', streamErr)
        result = await annotateApi.batchProcess(sessionId, batchRequest, controller.signal)
      }

      if (result.results.length > 0) {
        result.results[0].annotations.forEach((ann: AnnotationResult) => {
          updatedAnnotations[note.note_id][ann.prompt_type] = {
            note_id: note.note_id,
            prompt_type: ann.prompt_type,
            annotation_text: ann.annotation_text,
            values: ann.values,
            edited: false,
            is_negated: ann.is_negated,
            date_info: ann.date_info,
            evidence_text: ann.evidence_text,
            reasoning: ann.reasoning,
            raw_prompt: ann.raw_prompt,
            raw_response: ann.raw_response,
            evidence_spans: ann.evidence_spans || [],
            status: ann.status || 'success',
            evaluation_result: ann.evaluation_result,
            icdo3_code: ann.icdo3_code,
            derived_field_values: ann.derived_field_values,
          }
        })
        // Use the batch-level timing_breakdown which includes aggregated per-step sums
        // and per-prompt-type averages, falling back to first note's breakdown
        const hasBatchTiming = result.timing_breakdown &&
          ('note_count' in result.timing_breakdown || Object.keys(result.timing_breakdown).some(k => k.startsWith('sum_')))
        if (hasBatchTiming) {
          setLastTimingBreakdown(result.timing_breakdown ?? null)
        } else if (result.results[0]?.timing_breakdown) {
          setLastTimingBreakdown(result.results[0].timing_breakdown)
        }
      }

      // Final update
      setNoteProgress({
        current: totalPrompts,
        total: totalPrompts,
        currentPrompt: `Complete! (${result.total_time_seconds.toFixed(1)}s)`,
        percentage: 100,
      })

      const updatedSession = await sessionsApi.update(sessionId, updatedAnnotations)
      setSession(updatedSession)

      setTimeout(() => {
        setNoteProgress({ current: 0, total: 0, currentPrompt: '', percentage: 0 })
      }, 3000)
    } catch (err: any) {
      if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') {
        setError('Processing cancelled')
      } else {
        setError(err.response?.data?.detail || err.message || 'Processing failed')
      }
    } finally {
      setProcessing(false)
      abortControllerRef.current = null
    }
  }

  // Process a single prompt type for the current note
  const handleProcessSinglePrompt = async (promptType: string) => {
    if (!session) return
    const note = session.notes[selectedNoteIndex]
    if (!note) return

    setProcessingSinglePrompt(promptType)
    setError(null)

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const updatedAnnotations = { ...session.annotations }
      if (!updatedAnnotations[note.note_id]) {
        updatedAnnotations[note.note_id] = {}
      }

      const batchRequest = {
        note_ids: [note.note_id],
        prompt_types: [promptType],
        fewshot_k: 5,
        use_fewshots: !fastMode,
        fast_mode: fastMode,
      }

      let result: BatchProcessResponse
      try {
        result = await annotateApi.batchProcessStream(
          sessionId, batchRequest, undefined, controller.signal
        )
      } catch (streamErr: any) {
        if (streamErr.name === 'AbortError' || streamErr.code === 'ERR_CANCELED') throw streamErr
        result = await annotateApi.batchProcess(sessionId, batchRequest, controller.signal)
      }

      if (result.results.length > 0) {
        result.results[0].annotations.forEach((ann: AnnotationResult) => {
          updatedAnnotations[note.note_id][ann.prompt_type] = {
            note_id: note.note_id,
            prompt_type: ann.prompt_type,
            annotation_text: ann.annotation_text,
            values: ann.values,
            edited: false,
            is_negated: ann.is_negated,
            date_info: ann.date_info,
            evidence_text: ann.evidence_text,
            reasoning: ann.reasoning,
            raw_prompt: ann.raw_prompt,
            raw_response: ann.raw_response,
            evidence_spans: ann.evidence_spans || [],
            status: ann.status || 'success',
            evaluation_result: ann.evaluation_result,
            icdo3_code: ann.icdo3_code,
            derived_field_values: ann.derived_field_values,
          }
        })
      }

      const updatedSession = await sessionsApi.update(sessionId, updatedAnnotations)
      setSession(updatedSession)
    } catch (err: any) {
      if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') {
        setError('Processing cancelled')
      } else {
        setError(err.response?.data?.detail || err.message || 'Processing failed')
      }
    } finally {
      setProcessingSinglePrompt(null)
      abortControllerRef.current = null
    }
  }

  // Add a prompt type to a specific note: if previously excluded, un-exclude it; otherwise add as override
  const handleAddNotePrompt = async (noteId: string, promptType: string) => {
    if (!session) return
    const metadataUpdate: { note_prompt_overrides?: Record<string, string[]>; note_prompt_exclusions?: Record<string, string[]> } = {}

    // Check if this prompt was excluded from report_type_mapping
    const exclusions = { ...(session.note_prompt_exclusions || {}) }
    const noteExclusions = exclusions[noteId] || []
    if (noteExclusions.includes(promptType)) {
      // Un-exclude: remove from exclusions (restores it from report_type_mapping)
      exclusions[noteId] = noteExclusions.filter(pt => pt !== promptType)
      if (exclusions[noteId].length === 0) delete exclusions[noteId]
      metadataUpdate.note_prompt_exclusions = exclusions
    } else {
      // Add as per-note override
      const overrides = { ...(session.note_prompt_overrides || {}) }
      const noteOverrides = overrides[noteId] || []
      if (noteOverrides.includes(promptType)) return
      overrides[noteId] = [...noteOverrides, promptType]
      metadataUpdate.note_prompt_overrides = overrides
    }

    try {
      const updated = await sessionsApi.updateMetadata(sessionId, metadataUpdate)
      setSession(updated)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to add prompt')
    }
  }

  // Remove a prompt from this note: if it's an override, remove from overrides; if from report_type_mapping, add to exclusions
  const handleRemoveNotePrompt = async (noteId: string, promptType: string) => {
    if (!session) return
    const isOverride = session.note_prompt_overrides?.[noteId]?.includes(promptType) || false

    const metadataUpdate: { note_prompt_overrides?: Record<string, string[]>; note_prompt_exclusions?: Record<string, string[]> } = {}

    if (isOverride) {
      // Remove from overrides
      const overrides = { ...(session.note_prompt_overrides || {}) }
      overrides[noteId] = (overrides[noteId] || []).filter(pt => pt !== promptType)
      if (overrides[noteId].length === 0) delete overrides[noteId]
      metadataUpdate.note_prompt_overrides = overrides
    } else {
      // Add to exclusions (prompt comes from report_type_mapping)
      const exclusions = { ...(session.note_prompt_exclusions || {}) }
      const noteExclusions = exclusions[noteId] || []
      if (!noteExclusions.includes(promptType)) {
        exclusions[noteId] = [...noteExclusions, promptType]
      }
      metadataUpdate.note_prompt_exclusions = exclusions
    }

    // Also remove the annotation for this prompt on this note
    const updatedAnnotations = { ...session.annotations }
    if (updatedAnnotations[noteId]?.[promptType]) {
      const noteAnns = { ...updatedAnnotations[noteId] }
      delete noteAnns[promptType]
      updatedAnnotations[noteId] = noteAnns
      await sessionsApi.update(sessionId, updatedAnnotations)
    }

    try {
      const updated = await sessionsApi.updateMetadata(sessionId, metadataUpdate)
      setSession(updated)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to remove prompt')
    }
  }

  const handleProcessAll = async (forceReprocess = false) => {
    if (!session) return

    // Check if all notes already have annotations — ask for confirmation
    if (!forceReprocess) {
      const rtMapping = session.report_type_mapping || {}
      const allPromptTypes = session.prompt_types || []
      const allAnnotated = session.notes.every((note) => {
        const noteAnns = session.annotations[note.note_id]
        if (!noteAnns) return false
        // Use report_type_mapping to determine which prompts apply to this note
        const applicablePrompts = rtMapping[note.report_type] || allPromptTypes
        return applicablePrompts.every((pt) => noteAnns[pt] != null)
      })
      if (allAnnotated) {
        setReprocessConfirm(true)
        return
      }
    }

    const totalNotes = session.notes.length

    setProcessingAll(true)
    setError(null)
    setLastTimingBreakdown(null)
    setBatchTimingReport(null)
    const controller = new AbortController()
    abortControllerRef.current = controller

    setProgress({
      current: 0,
      total: totalNotes,
      currentNote: 'Starting sequential processing...',
      percentage: 0,
      timeRemaining: 0,
    })

    const startTime = Date.now()
    const processingTimes: number[] = []

    try {
      // Use sequential endpoint — server saves after each note (crash resilient)
      const sequentialReq = {
        fewshot_k: 5,
        use_fewshots: !fastMode,
        fast_mode: fastMode,
        skip_annotated: !forceReprocess, // Resume capability: skip already-annotated notes
      }

      const result = await annotateApi.sequentialProcessStream(
        sessionId,
        sequentialReq,
        (prog: SequentialProgressEvent) => {
          // Track processing times for time estimation
          if (prog.processing_time_seconds && prog.status === 'success') {
            processingTimes.push(prog.processing_time_seconds)
          }

          const avgTime = processingTimes.length > 0
            ? processingTimes.reduce((a, b) => a + b, 0) / processingTimes.length
            : 0
          const remaining = prog.total - prog.completed
          const estimatedTimeRemaining = Math.round(avgTime * remaining)

          const statusLabel = prog.status === 'error'
            ? `ERROR: ${prog.error_message}`
            : prog.status === 'skipped'
              ? 'skipped'
              : `${prog.annotations_count || 0} prompts`

          setProgress({
            current: prog.completed,
            total: prog.total,
            currentNote: `Note ${prog.completed}/${prog.total}: ${prog.note_id} — ${statusLabel}`,
            percentage: Math.round(prog.percentage),
            timeRemaining: estimatedTimeRemaining,
          })

          // Progressive refresh: update session periodically so annotations
          // become available in the UI while processing continues.
          // Use startTransition to keep the refresh low-priority (won't block progress bar or UI).
          // Scale interval with session size to avoid excessive re-renders.
          const REFRESH_INTERVAL = totalNotes > 50 ? 10 : 5
          if (prog.status === 'success' && (prog.completed % REFRESH_INTERVAL === 0 || prog.completed === prog.total)) {
            sessionsApi.get(sessionId).then(refreshed => {
              startTransition(() => setSession(refreshed))
            }).catch(() => {})
          }
        },
        controller.signal,
      )

      // Refresh session from server (annotations were saved server-side per note)
      const refreshedSession = await sessionsApi.get(sessionId)
      setSession(refreshedSession)

      const totalTimeSec = (Date.now() - startTime) / 1000
      const totalTime = totalTimeSec.toFixed(1)
      const errorCount = result.errors || 0
      const statusMsg = errorCount > 0
        ? `Done with ${errorCount} error(s) (${totalTime}s)`
        : `Complete! (${totalTime}s)`

      setProgress({
        current: result.processed + result.errors,
        total: result.processed + result.errors,
        currentNote: controller.signal.aborted ? `Cancelled after ${totalTime}s` : statusMsg,
        percentage: 100,
        timeRemaining: 0,
      })

      // Build timing report
      const ts = result.timing_summary
      setBatchTimingReport({
        totalTime: totalTimeSec,
        processed: result.processed,
        skipped: result.skipped,
        errors: result.errors,
        avgPerNote: ts?.avg_per_note ?? (processingTimes.length > 0 ? processingTimes.reduce((a, b) => a + b, 0) / processingTimes.length : 0),
        minPerNote: ts?.min_per_note ?? (processingTimes.length > 0 ? Math.min(...processingTimes) : 0),
        maxPerNote: ts?.max_per_note ?? (processingTimes.length > 0 ? Math.max(...processingTimes) : 0),
      })
    } catch (err: any) {
      if (err.name === 'AbortError' || err.name === 'CanceledError' || err.code === 'ERR_CANCELED') {
        setError('Batch processing cancelled. Already-processed notes have been saved.')
        // Refresh session to show saved progress
        try {
          const refreshedSession = await sessionsApi.get(sessionId)
          setSession(refreshedSession)
        } catch { /* ignore refresh errors on cancel */ }
      } else {
        setError(err.response?.data?.detail || err.message || 'Batch processing failed')
        // Still refresh — some notes may have been saved before the error
        try {
          const refreshedSession = await sessionsApi.get(sessionId)
          setSession(refreshedSession)
        } catch { /* ignore refresh errors */ }
      }
    } finally {
      setProcessingAll(false)
      abortControllerRef.current = null
    }
  }

  const handleSaveAnnotation = async (promptType: string, values: string[]) => {
    if (!session) return

    const note = session.notes[selectedNoteIndex]
    if (!note) return

    const updatedAnnotations = { ...session.annotations }
    if (!updatedAnnotations[note.note_id]) {
      updatedAnnotations[note.note_id] = {}
    }

    // Reconstruct annotation text from values
    const annotationText = values.join(', ')

    // Preserve existing fields (is_negated, date_info, evidence_text, reasoning, raw_prompt, raw_response, evaluation_result, icdo3_code)
    const existingAnnotation = updatedAnnotations[note.note_id][promptType] || {}
    updatedAnnotations[note.note_id][promptType] = {
      ...existingAnnotation,
      note_id: note.note_id,
      prompt_type: promptType,
      annotation_text: annotationText,
      values: values.map((v) => ({
        value: v,
        evidence_spans: [],
        reasoning: undefined,
      })),
      edited: true,
      edited_at: new Date().toISOString(),
      // Preserve these fields even when editing
      is_negated: existingAnnotation.is_negated,
      date_info: existingAnnotation.date_info,
      evidence_text: existingAnnotation.evidence_text,
      reasoning: existingAnnotation.reasoning,
      raw_prompt: existingAnnotation.raw_prompt,
      raw_response: existingAnnotation.raw_response,
      evidence_spans: existingAnnotation.evidence_spans || [],
      status: existingAnnotation.status || 'success',
      evaluation_result: existingAnnotation.evaluation_result,  // Preserve evaluation results
      icdo3_code: existingAnnotation.icdo3_code,  // Preserve ICD-O-3 code information
    }

    try {
      const updatedSession = await sessionsApi.update(sessionId, updatedAnnotations)
      setSession(updatedSession)
    } catch (err: any) {
      setError(err.message || 'Failed to save annotation')
    }
  }

  const handleSpanClick = (span: EvidenceSpan) => {
    setSelectedPromptType(span.prompt_type)
  }

  // Handle export download
  const handleExport = async (mode: 'labels' | 'codes' | 'session', skipValidation = false) => {
    // Pre-export diagnosis validation for labels/codes exports
    if ((mode === 'labels' || mode === 'codes') && !skipValidation) {
      try {
        const report = await sessionsApi.getDiagnoses(sessionId)
        if (report.needs_review > 0) {
          setDiagnosisValidation({ mode, report })
          return
        }
      } catch (err) {
        console.warn('Diagnosis validation check failed, proceeding with export:', err)
      }

      // Pre-export cardinality validation
      try {
        const validation = await sessionsApi.validateExport(sessionId)
        if (!validation.valid) {
          setExportConflicts(validation.conflicts)
          return
        }
      } catch (err) {
        console.warn('Cardinality validation check failed, proceeding with export:', err)
      }
    }

    setExporting(mode)
    try {
      let blob: Blob
      let filename: string
      let excludedRows: import('@/lib/api').ExcludedRow[] = []
      if (mode === 'labels') {
        const result = await sessionsApi.exportLabels(sessionId)
        blob = result.blob
        excludedRows = result.excludedRows
        filename = `${sessionId}_validated.csv`
      } else if (mode === 'codes') {
        const result = await sessionsApi.exportCodes(sessionId)
        blob = result.blob
        excludedRows = result.excludedRows
        filename = `${sessionId}_coded.csv`
      } else {
        blob = await sessionsApi.exportSession(sessionId)
        filename = `session_${sessionId}.json`
      }
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)

      // Show exclusion report modal if any rows were filtered out
      if (excludedRows.length > 0) {
        setExclusionReport(excludedRows)
      }
    } catch (err: any) {
      // Handle 409 conflict errors (cardinality violations) — responseType is blob so parse it
      if (err.response?.status === 409) {
        try {
          const text = err.response.data instanceof Blob
            ? await err.response.data.text()
            : JSON.stringify(err.response.data)
          const detail = JSON.parse(text)?.detail
          if (detail?.conflicts) {
            setExportConflicts(detail.conflicts)
            return
          }
        } catch { /* fall through to generic error */ }
      }
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : detail?.message || err.message || 'Export failed')
    } finally {
      setExporting(null)
    }
  }

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="text-center text-gray-500">Loading session...</div>
      </div>
    )
  }

  if (!session) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="text-center text-red-600">Session not found</div>
      </div>
    )
  }

  const currentNote = session.notes[selectedNoteIndex]
  if (!currentNote) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="text-center text-red-600">Note not found</div>
      </div>
    )
  }

  // Calculate overall evaluation statistics (only in evaluation mode)
  const evaluationStats = session.evaluation_mode === 'evaluation' ? (() => {
    let totalAnnotations = 0
    let totalMatches = 0
    let totalMismatches = 0
    let totalSimilarity = 0
    let similarityCount = 0

    Object.values(session.annotations).forEach((noteAnns) => {
      Object.values(noteAnns).forEach((ann: any) => {
        if (ann.evaluation_result) {
          totalAnnotations++
          if (ann.evaluation_result.overall_match) {
            totalMatches++
          } else {
            totalMismatches++
          }
          if (ann.evaluation_result.similarity_score !== undefined) {
            totalSimilarity += ann.evaluation_result.similarity_score
            similarityCount++
          }
        }
      })
    })

    return {
      totalAnnotations,
      totalMatches,
      totalMismatches,
      matchRate: totalAnnotations > 0 ? (totalMatches / totalAnnotations) * 100 : 0,
      avgSimilarity: similarityCount > 0 ? totalSimilarity / similarityCount : 0,
    }
  })() : null

  // Collect all evidence spans from annotations
  const allSpans: EvidenceSpan[] = []
  const noteAnnotations = session.annotations[currentNote.note_id] || {}
  Object.values(noteAnnotations).forEach((ann) => {
    // Evidence spans are stored directly on the annotation object
    if (ann.evidence_spans && Array.isArray(ann.evidence_spans) && ann.evidence_spans.length > 0) {
      allSpans.push(...ann.evidence_spans)
    } else if (ann.evidence_text && currentNote.text) {
      // If no spans but we have evidence_text, try to find it in the note
      // This handles old sessions that don't have evidence_spans saved
      const evidenceText = ann.evidence_text
      const noteText = currentNote.text

      // Simple case-insensitive search
      const evidenceLower = evidenceText.toLowerCase()
      const noteLower = noteText.toLowerCase()
      const start = noteLower.indexOf(evidenceLower)

      if (start !== -1) {
        // Found it - create a span
        allSpans.push({
          start,
          end: start + evidenceText.length,
          text: noteText.substring(start, start + evidenceText.length),
          prompt_type: ann.prompt_type || '',
        })
      }
    }
    // Also check values for backward compatibility
    if (ann.values) {
      ann.values.forEach((val) => {
        if (val.evidence_spans && Array.isArray(val.evidence_spans)) {
          allSpans.push(...val.evidence_spans)
        }
      })
    }
  })

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-6">
        <div className="flex justify-between items-start mb-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{session.name}</h1>
            <div className="flex items-center gap-2 mt-1">
              <p className="text-sm text-gray-500">
                Note {selectedNoteIndex + 1} of {session.notes.length}
              </p>
              <span className="text-sm text-gray-500">•</span>
              <p className="text-sm text-gray-500">
                {session.prompt_types.length} prompt type{session.prompt_types.length !== 1 ? 's' : ''}
              </p>
              <button
                onClick={() => setShowPromptTypesModal(true)}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium"
              >
                Manage
              </button>
              {session.evaluation_mode === 'evaluation' && (
                <div className="flex items-center gap-2">
                  <span className="text-xs px-2 py-1 rounded bg-blue-100 text-blue-800 font-medium">
                    Evaluation Mode
                  </span>
                  {evaluationStats && evaluationStats.totalAnnotations > 0 && (
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-gray-600">
                        {evaluationStats.totalMatches}/{evaluationStats.totalAnnotations} matches
                      </span>
                      <span className="text-gray-500">
                        ({evaluationStats.matchRate.toFixed(1)}%)
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
          {/* Navigation */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelectedNoteIndex(Math.max(0, selectedNoteIndex - 1))}
              disabled={selectedNoteIndex === 0}
              className="px-4 py-2 border border-gray-300 rounded-md text-sm disabled:opacity-50"
            >
              Previous
            </button>
            <button
              onClick={() =>
                setSelectedNoteIndex(
                  Math.min(session.notes.length - 1, selectedNoteIndex + 1)
                )
              }
              disabled={selectedNoteIndex === session.notes.length - 1}
              className="px-4 py-2 border border-gray-300 rounded-md text-sm disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>

        {/* Action bar: exports + diagnosis */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <button
            onClick={() => setShowDiagnosisPanel(prev => !prev)}
            className={`px-3 py-1.5 border rounded-md text-sm font-medium ${
              showDiagnosisPanel
                ? 'border-primary-500 bg-primary-50 text-primary-700'
                : 'border-purple-300 text-purple-700 hover:bg-purple-50'
            }`}
          >
            Patient Diagnoses
          </button>
          <div className="w-px h-6 bg-gray-200" />
          <button
            onClick={() => handleExport('labels')}
            disabled={exporting !== null}
            className="px-3 py-1.5 border border-gray-300 rounded-md text-sm hover:bg-gray-50 disabled:opacity-50"
          >
            {exporting === 'labels' ? 'Exporting...' : 'Export Labels CSV'}
          </button>
          <button
            onClick={() => handleExport('codes')}
            disabled={exporting !== null}
            className="px-3 py-1.5 border border-indigo-300 text-indigo-700 rounded-md text-sm hover:bg-indigo-50 disabled:opacity-50"
          >
            {exporting === 'codes' ? 'Exporting...' : 'Export Codes CSV'}
          </button>
          <button
            onClick={() => handleExport('session')}
            disabled={exporting !== null}
            className="px-3 py-1.5 border border-green-300 text-green-700 rounded-md text-sm hover:bg-green-50 disabled:opacity-50"
          >
            {exporting === 'session' ? 'Exporting...' : 'Export Session JSON'}
          </button>
        </div>

        {/* Process All Button and Progress */}
        <div className="bg-white rounded-lg shadow p-4 mb-4">
          <div className="flex justify-between items-center mb-2">
            <div className="flex-1">
              <h3 className="text-sm font-semibold text-gray-700">
                Batch Processing
              </h3>
              <p className="text-xs text-gray-500">
                Process all {session.notes.length} notes with all {session.prompt_types.length} prompt types
              </p>
              {/* Evaluation Statistics */}
              {session.evaluation_mode === 'evaluation' && evaluationStats && evaluationStats.totalAnnotations > 0 && (
                <div className="mt-2 flex gap-4 text-xs">
                  <div className="flex items-center gap-1">
                    <span className="text-gray-600">Total:</span>
                    <span className="font-medium">{evaluationStats.totalAnnotations}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-green-600">✓ Matches:</span>
                    <span className="font-medium text-green-700">{evaluationStats.totalMatches}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-red-600">✗ Mismatches:</span>
                    <span className="font-medium text-red-700">{evaluationStats.totalMismatches}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-gray-600">Match Rate:</span>
                    <span className="font-medium">{evaluationStats.matchRate.toFixed(1)}%</span>
                  </div>
                  {evaluationStats.avgSimilarity > 0 && (
                    <div className="flex items-center gap-1">
                      <span className="text-gray-600">Avg Similarity:</span>
                      <span className="font-medium">{evaluationStats.avgSimilarity.toFixed(3)}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className="flex gap-2 items-center">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <div className="relative">
                  <input
                    type="checkbox"
                    checked={fastMode}
                    onChange={(e) => setFastMode(e.target.checked)}
                    disabled={processing || processingAll || processingSinglePrompt !== null}
                    className="sr-only peer"
                  />
                  <div className="w-9 h-5 bg-gray-300 rounded-full peer peer-checked:bg-amber-500 peer-disabled:opacity-50 transition-colors" />
                  <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full shadow peer-checked:translate-x-4 transition-transform" />
                </div>
                <span className={`text-xs font-semibold ${fastMode ? 'text-amber-600' : 'text-gray-500'}`}>
                  {fastMode ? 'FAST' : 'Standard'}
                </span>
              </label>
              <button
                onClick={() => handleProcessAll()}
                disabled={processingAll || session.notes.length === 0 || processingSinglePrompt !== null}
                className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
              >
                {processingAll ? 'Processing...' : 'Process All Notes'}
              </button>
              {processingAll && (
                <button
                  onClick={handleCancelProcessing}
                  className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm font-medium"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>

          {processingAll && (
            <div className="mt-4">
              <div className="flex justify-between text-xs text-gray-600 mb-1">
                <span>{progress.currentNote}</span>
                <span>
                  {progress.current} / {progress.total} tasks ({progress.percentage}%)
                </span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2.5">
                <div
                  className="bg-green-600 h-2.5 rounded-full transition-all duration-300"
                  style={{ width: `${progress.percentage}%` }}
                />
              </div>
              <div className="flex justify-between text-xs text-gray-500 mt-1">
                <span>Elapsed: {formatTimeRemaining(elapsedTime)}</span>
                {progress.timeRemaining > 0 && (
                  <span>Estimated remaining: {formatTimeRemaining(progress.timeRemaining)}</span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Batch timing report (shown after batch processing completes) */}
      {!processingAll && batchTimingReport && (
        <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex justify-between items-start">
            <div>
              <h3 className="text-sm font-semibold text-green-800">
                Processing Complete &mdash; {batchTimingReport.processed} notes in {formatTimeRemaining(Math.round(batchTimingReport.totalTime))}
              </h3>
              <div className="mt-1 grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-1 text-xs text-green-700">
                <div>Processed: <span className="font-medium">{batchTimingReport.processed}</span></div>
                <div>Skipped: <span className="font-medium">{batchTimingReport.skipped}</span></div>
                <div>Errors: <span className="font-medium">{batchTimingReport.errors}</span></div>
                <div>Avg/note: <span className="font-mono font-medium">{batchTimingReport.avgPerNote.toFixed(1)}s</span></div>
                <div>Fastest: <span className="font-mono font-medium">{batchTimingReport.minPerNote.toFixed(1)}s</span></div>
                <div>Slowest: <span className="font-mono font-medium">{batchTimingReport.maxPerNote.toFixed(1)}s</span></div>
              </div>
            </div>
            <button
              onClick={() => setBatchTimingReport(null)}
              className="text-green-400 hover:text-green-600 text-sm ml-2"
              title="Dismiss"
            >
              &times;
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
          {error}
        </div>
      )}

      {/* Patient Diagnosis Panel (above the note grid) */}
      {showDiagnosisPanel && session && (
        <div className="mb-4">
          <PatientDiagnosisPanel
            sessionId={sessionId}
            session={session}
            onDiagnosisUpdate={() => loadSession()}
            onNavigateToAnnotation={navigateToAnnotation}
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Panel - Text Viewer */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="mb-4 flex justify-between items-center">
            <h2 className="text-lg font-semibold text-gray-900">Clinical Note</h2>
            <div className="flex gap-2">
              <button
                onClick={handleProcessNote}
                disabled={processing || processingAll || processingSinglePrompt !== null}
                className="px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
              >
                {processing ? 'Processing...' : 'Process Note'}
              </button>
              {processing && (
                <button
                  onClick={handleCancelProcessing}
                  className="px-3 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>

          {/* Progress feedback for single note processing */}
          {processing && noteProgress.total > 0 && (
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md">
              <div className="flex justify-between text-xs text-gray-700 mb-1">
                <span>
                  {noteProgress.currentPrompt || 'Starting...'}
                </span>
                <span>
                  {noteProgress.current} / {noteProgress.total} prompts ({noteProgress.percentage}%)
                </span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${noteProgress.percentage}%` }}
                />
              </div>
            </div>
          )}

          {/* Timing breakdown (shown after processing completes) */}
          {!processing && lastTimingBreakdown && (
            <div className="mb-4 p-3 bg-gray-50 border border-gray-200 rounded-md">
              <button
                onClick={() => setLastTimingBreakdown(null)}
                className="flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-800 mb-1"
              >
                Timing Breakdown
                <span className="text-gray-400 ml-1">(click to dismiss)</span>
              </button>
              {/* Summary stats */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs text-gray-600">
                {Object.entries(lastTimingBreakdown)
                  .filter(([k]) => !k.startsWith('avg_') && !k.startsWith('sum_') && k !== 'prompt_count')
                  .sort(([, a], [, b]) => b - a)
                  .map(([step, duration]) => (
                    <div key={step} className="flex justify-between">
                      <span className="text-gray-500">{step.replace(/_/g, ' ')}:</span>
                      <span className="font-mono font-medium">{duration.toFixed(2)}s</span>
                    </div>
                  ))}
              </div>
              {/* Per-prompt-type averages (batch mode) */}
              {Object.entries(lastTimingBreakdown).some(([k]) => k.startsWith('avg_')) && (
                <div className="mt-2 pt-2 border-t border-gray-200">
                  <div className="text-xs font-medium text-gray-500 mb-1">Avg time per prompt type:</div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs text-gray-600">
                    {Object.entries(lastTimingBreakdown)
                      .filter(([k]) => k.startsWith('avg_'))
                      .sort(([, a], [, b]) => b - a)
                      .map(([step, duration]) => (
                        <div key={step} className="flex justify-between">
                          <span className="text-gray-500">{step.replace('avg_', '').replace(/_/g, ' ')}:</span>
                          <span className="font-mono font-medium">{duration.toFixed(2)}s</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}
              {/* Aggregated step totals (batch mode) */}
              {Object.entries(lastTimingBreakdown).some(([k]) => k.startsWith('sum_')) && (
                <div className="mt-2 pt-2 border-t border-gray-200">
                  <div className="text-xs font-medium text-gray-500 mb-1">Total time per step (all notes):</div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs text-gray-600">
                    {Object.entries(lastTimingBreakdown)
                      .filter(([k]) => k.startsWith('sum_'))
                      .sort(([, a], [, b]) => b - a)
                      .map(([step, duration]) => (
                        <div key={step} className="flex justify-between">
                          <span className="text-gray-500">{step.replace('sum_', '').replace(/_/g, ' ')}:</span>
                          <span className="font-mono font-medium">{duration.toFixed(2)}s</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="mb-2 text-xs text-gray-500">
            <span>Note ID: {currentNote.note_id}</span>
            <span className="ml-4">Report Type: {currentNote.report_type}</span>
            <span className="ml-4">Date: {currentNote.date}</span>
          </div>
          <div className="border border-gray-200 rounded-lg p-4 max-h-[600px] overflow-y-auto bg-gray-50">
            <TextHighlighter
              text={currentNote.text}
              spans={allSpans}
              selectedPromptType={selectedPromptType || undefined}
              onSpanClick={handleSpanClick}
            />
          </div>
        </div>

        {/* Right Panel - Annotations */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Annotations</h2>
          <div className="space-y-4 max-h-[700px] overflow-y-auto">
            {getPromptTypesForNote(currentNote).length === 0 ? (
              <div className="text-sm text-gray-500">
                No prompt types selected. Process the note to generate annotations.
              </div>
            ) : (
              getPromptTypesForNote(currentNote).map((promptType) => {
                const annotation = noteAnnotations[promptType]
                const isOverride = session.note_prompt_overrides?.[currentNote.note_id]?.includes(promptType) || false
                const isProcessingThis = processingSinglePrompt === promptType
                const anyProcessing = processing || processingAll || processingSinglePrompt !== null
                // Extract expected annotation for this specific prompt type
                const expectedAnnotation = extractExpectedAnnotation(
                  currentNote.annotations || null,
                  promptType
                )

                return (
                  <div key={promptType} id={`annotation-${promptType}`} className="transition-shadow duration-300">
                    {/* Per-prompt header with Process button */}
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-gray-500">{promptType}</span>
                        {isOverride && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded font-medium">per-note</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          className="text-xs px-1.5 py-0.5 text-red-500 hover:text-red-700 hover:bg-red-50 rounded disabled:opacity-50"
                          onClick={(e) => { e.stopPropagation(); handleRemoveNotePrompt(currentNote.note_id, promptType) }}
                          disabled={anyProcessing}
                          title={isOverride ? "Remove this per-note prompt" : "Exclude this prompt from this note"}
                        >
                          Remove
                        </button>
                        <button
                          className="text-xs px-2 py-0.5 bg-blue-50 text-blue-600 rounded hover:bg-blue-100 disabled:opacity-50 flex items-center gap-1"
                          onClick={() => handleProcessSinglePrompt(promptType)}
                          disabled={anyProcessing}
                          title="Process only this prompt"
                        >
                          {isProcessingThis ? (
                            <>
                              <svg className="animate-spin h-3 w-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                              </svg>
                              Processing...
                            </>
                          ) : (
                            'Process'
                          )}
                        </button>
                      </div>
                    </div>
                    <AnnotationViewer
                      annotation={
                        annotation
                          ? {
                            prompt_type: annotation.prompt_type,
                            annotation_text: annotation.annotation_text,
                            values: annotation.values || [],
                            evidence_spans: annotation.evidence_spans || annotation.values?.flatMap((v) => v.evidence_spans || []) || [],
                            reasoning: annotation.reasoning,
                            is_negated: annotation.is_negated,
                            date_info: annotation.date_info,
                            evidence_text: annotation.evidence_text,
                            raw_prompt: annotation.raw_prompt,
                            raw_response: annotation.raw_response,
                            status: annotation.status || 'success',
                            evaluation_result: annotation.evaluation_result,
                            icdo3_code: annotation.icdo3_code,
                            derived_field_values: annotation.derived_field_values,
                          }
                          : {
                            prompt_type: promptType,
                            annotation_text: '',
                            values: [],
                            evidence_spans: [],
                            reasoning: undefined,
                            is_negated: undefined,
                            date_info: undefined,
                            evidence_text: undefined,
                            raw_prompt: undefined,
                            raw_response: undefined,
                            status: undefined,
                            evaluation_result: undefined,
                            icdo3_code: undefined,
                          }
                      }
                      noteText={currentNote.text}
                      expectedAnnotation={expectedAnnotation}
                      onSave={(values) => handleSaveAnnotation(promptType, values)}
                      onSelectSpan={handleSpanClick}
                      sessionId={sessionId}
                      noteId={currentNote.note_id}
                    />
                  </div>
                )
              })
            )}

            {/* Add/restore prompt dropdown */}
            {(() => {
              const currentPrompts = getPromptTypesForNote(currentNote)
              const excludedPrompts = session.note_prompt_exclusions?.[currentNote.note_id] || []
              // Combine available prompts + excluded prompts (which may not be in availablePrompts if from another center)
              const allCandidates = new Set([
                ...availablePrompts.map(p => p.prompt_type),
                ...excludedPrompts,
              ])
              const addablePrompts = [...allCandidates].filter(pt => !currentPrompts.includes(pt))
              if (addablePrompts.length === 0) return null
              // Show excluded (restorable) prompts first
              const sortedPrompts = [
                ...addablePrompts.filter(pt => excludedPrompts.includes(pt)),
                ...addablePrompts.filter(pt => !excludedPrompts.includes(pt)),
              ]
              return (
                <div className="mt-3 pt-3 border-t border-gray-200">
                  <select
                    className="text-sm border border-gray-300 rounded px-2 py-1.5 w-full text-gray-600 bg-white hover:border-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    value=""
                    onChange={(e) => {
                      if (e.target.value) {
                        handleAddNotePrompt(currentNote.note_id, e.target.value)
                      }
                    }}
                    disabled={processing || processingAll || processingSinglePrompt !== null}
                  >
                    <option value="">+ Add prompt to this note...</option>
                    {sortedPrompts.map(pt => (
                      <option key={pt} value={pt}>{excludedPrompts.includes(pt) ? `↩ ${pt} (restore)` : pt}</option>
                    ))}
                  </select>
                </div>
              )
            })()}
          </div>
        </div>
      </div>

      {/* Prompt Types & Report Mapping Management Modal */}
      {showPromptTypesModal && (
        <ManagePromptTypesModal
          session={session}
          availablePrompts={availablePrompts}
          center={session.center || center}
          onClose={() => setShowPromptTypesModal(false)}
          onSave={async (reportTypeMapping) => {
            try {
              const updatedSession = await sessionsApi.updateMetadata(sessionId, {
                report_type_mapping: reportTypeMapping,
              })
              setSession(updatedSession)
              setShowPromptTypesModal(false)
            } catch (err: any) {
              setError(err.response?.data?.detail || err.message || 'Failed to update prompt types')
            }
          }}
          error={error}
        />
      )}

      {/* Reprocess Confirmation Modal */}
      {reprocessConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900">All notes already annotated</h3>
              <p className="text-sm text-gray-500 mt-1">
                All notes have been processed. Do you want to re-process them? This will overwrite the existing annotations.
              </p>
            </div>
            <div className="px-6 py-4 flex justify-end gap-2">
              <button
                onClick={() => setReprocessConfirm(false)}
                className="px-4 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setReprocessConfirm(false)
                  handleProcessAll(true)
                }}
                className="px-4 py-2 text-sm bg-primary-600 text-white rounded-md hover:bg-primary-700"
              >
                Re-process All
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Cardinality Conflict Modal */}
      {exportConflicts && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
            <div className="px-6 py-4 border-b border-red-200 bg-red-50 rounded-t-lg">
              <h3 className="text-lg font-semibold text-red-700">Export Blocked: Data Conflicts Detected</h3>
              <p className="text-sm text-red-600 mt-1">
                {exportConflicts.length} conflict(s) must be resolved before exporting.
                Each variable must have a single unique value per entity instance.
              </p>
            </div>

            <div className="px-6 py-4 overflow-y-auto flex-1">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-500 border-b">
                    <th className="pb-2 pr-3">Patient</th>
                    <th className="pb-2 pr-3">Variable</th>
                    <th className="pb-2 pr-3">Date</th>
                    <th className="pb-2 pr-3">Type</th>
                    <th className="pb-2">Conflicting Values</th>
                  </tr>
                </thead>
                <tbody>
                  {exportConflicts.map((c, i) => (
                    <tr key={i} className="border-b border-gray-100">
                      <td className="py-2 pr-3 font-mono text-xs">{c.patient_id}</td>
                      <td className="py-2 pr-3 text-xs">{c.core_variable}</td>
                      <td className="py-2 pr-3 text-xs text-gray-500">
                        {c.date_ref || <span className="italic">N/A</span>}
                      </td>
                      <td className="py-2 pr-3">
                        {c.conflict_type === 'non_repeatable' ? (
                          <span className="inline-block px-1.5 py-0.5 text-xs rounded bg-red-100 text-red-700">
                            Unique entity
                          </span>
                        ) : (
                          <span className="inline-block px-1.5 py-0.5 text-xs rounded bg-orange-100 text-orange-700">
                            Same date
                          </span>
                        )}
                      </td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-1">
                          {c.conflicting_values.map((v, j) => (
                            <span key={j} className="inline-block px-1.5 py-0.5 text-xs rounded bg-gray-100 text-gray-700 font-mono">
                              {v}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="px-6 py-3 border-t border-gray-200 bg-gray-50 rounded-b-lg">
              <p className="text-xs text-gray-500 mb-3">
                To resolve: edit the conflicting annotations in the notes so that each variable has a single consistent value.
                For unique entities (Patient, Diagnosis, etc.), only one value is allowed across all notes.
                For repeatable entities (Surgery, Radiotherapy, etc.), different values require different dates.
              </p>
              <div className="flex justify-end">
                <button
                  onClick={() => setExportConflicts(null)}
                  className="px-4 py-2 text-sm bg-red-600 text-white rounded-md hover:bg-red-700"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Pre-Export Diagnosis Validation Dialog */}
      {diagnosisValidation && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-lg w-full">
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="text-lg font-semibold text-yellow-700">Unresolved Patient Diagnoses</h3>
              <p className="text-sm text-gray-500 mt-1">
                {diagnosisValidation.report.needs_review} patient(s) have unresolved diagnoses.
                These will appear as &quot;UNRESOLVED&quot; in the export.
              </p>
            </div>
            <div className="px-6 py-4 max-h-60 overflow-y-auto">
              {diagnosisValidation.report.patients
                .filter(p => p.status === 'needs_review')
                .map(p => (
                  <div key={p.patient_id} className="py-2 border-b last:border-0">
                    <span className="font-mono text-xs text-gray-700">{p.patient_id}</span>
                    {p.review_reasons.map((r, i) => (
                      <div key={i} className="text-xs text-yellow-600 ml-4">- {r}</div>
                    ))}
                  </div>
                ))}
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-2">
              <button
                onClick={() => setDiagnosisValidation(null)}
                className="px-4 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setDiagnosisValidation(null)
                  setShowDiagnosisPanel(true)
                }}
                className="px-4 py-2 text-sm border border-primary-300 text-primary-700 rounded-md hover:bg-primary-50"
              >
                Review Diagnoses
              </button>
              <button
                onClick={() => {
                  const mode = diagnosisValidation.mode
                  setDiagnosisValidation(null)
                  handleExport(mode, true)
                }}
                className="px-4 py-2 text-sm bg-yellow-600 text-white rounded-md hover:bg-yellow-700"
              >
                Export Anyway
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Exclusion Report Modal */}
      {exclusionReport && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Export Exclusion Report</h3>
                <p className="text-sm text-gray-500 mt-1">
                  {exclusionReport.length} row(s) excluded from the export
                </p>
              </div>
              <button
                onClick={() => setExclusionReport(null)}
                className="text-gray-400 hover:text-gray-600 text-xl leading-none"
              >
                &times;
              </button>
            </div>

            <div className="px-6 py-4 overflow-y-auto flex-1">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-500 border-b">
                    <th className="pb-2 pr-3">Patient</th>
                    <th className="pb-2 pr-3">Variable</th>
                    <th className="pb-2 pr-3">Value</th>
                    <th className="pb-2">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {exclusionReport.map((row, i) => (
                    <tr key={i} className="border-b border-gray-100">
                      <td className="py-2 pr-3 font-mono text-xs">{row.patient_id}</td>
                      <td className="py-2 pr-3">{row.variable}</td>
                      <td className="py-2 pr-3 text-gray-600 italic">
                        {row.value || '(empty)'}
                      </td>
                      <td className="py-2 text-gray-500 text-xs">{row.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="px-6 py-3 border-t border-gray-200 flex justify-end gap-3">
              <button
                onClick={() => {
                  const lines = [
                    `Export Exclusion Report`,
                    `Generated: ${new Date().toISOString()}`,
                    `Total excluded: ${exclusionReport.length}`,
                    ``,
                    `${'Patient'.padEnd(15)} ${'Variable'.padEnd(50)} ${'Value'.padEnd(25)} Reason`,
                    `${'─'.repeat(15)} ${'─'.repeat(50)} ${'─'.repeat(25)} ${'─'.repeat(40)}`,
                    ...exclusionReport.map(
                      (r) =>
                        `${(r.patient_id || '').padEnd(15)} ${r.variable.padEnd(50)} ${(r.value || '(empty)').padEnd(25)} ${r.reason}`
                    ),
                  ]
                  const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
                  const url = window.URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = `exclusion_report_${sessionId}.txt`
                  document.body.appendChild(a)
                  a.click()
                  a.remove()
                  window.URL.revokeObjectURL(url)
                }}
                className="px-4 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
              >
                Download as TXT
              </button>
              <button
                onClick={() => setExclusionReport(null)}
                className="px-4 py-2 text-sm bg-primary-600 text-white rounded-md hover:bg-primary-700"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

