'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'next/navigation'
import { sessionsApi, annotateApi, promptsApi, presetsApi } from '@/lib/api'
import { useDefaultCenter } from '@/lib/useDefaultCenter'
import type { SessionData, AnnotationResult, EvidenceSpan, PromptInfo, ICDO3CodeInfo, UnifiedICDO3Code } from '@/lib/api'
import ManagePromptTypesModal from '@/components/ManagePromptTypesModal'
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
  const [exporting, setExporting] = useState<'labels' | 'codes' | null>(null)
  // Track unified ICD-O-3 codes per note
  const [unifiedCodes, setUnifiedCodes] = useState<Record<string, UnifiedICDO3Code>>({})
  // AbortController for cancelling in-flight requests
  const abortControllerRef = useRef<AbortController | null>(null)
  // Last batch timing breakdown
  const [lastTimingBreakdown, setLastTimingBreakdown] = useState<Record<string, number> | null>(null)

  useEffect(() => {
    loadSession()
  }, [sessionId])

  useEffect(() => {
    loadAvailablePrompts()
  }, [center])

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

  // Get the prompt types applicable to a specific note based on report_type_mapping
  const getPromptTypesForNote = (note: { report_type?: string }): string[] => {
    if (!session) return []
    const mapping = session.report_type_mapping
    if (mapping && note.report_type && mapping[note.report_type]) {
      return mapping[note.report_type]
    }
    // No mapping exists for this report type — return empty so only explicitly selected prompts run
    return []
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
      currentPrompt: `Processing ${totalPrompts} prompts in parallel...`,
      percentage: 10,
    })

    try {
      const updatedAnnotations = { ...session.annotations }
      if (!updatedAnnotations[note.note_id]) {
        updatedAnnotations[note.note_id] = {}
      }

      // Send ALL prompts in a single batch call (processed in parallel on backend)
      const result = await annotateApi.batchProcess(sessionId, {
        note_ids: [note.note_id],
        prompt_types: notePromptTypes,
        fewshot_k: 5,
        use_fewshots: true,
      }, controller.signal)

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
          }
        })
        if (result.results[0].timing_breakdown) {
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

  const handleProcessAll = async () => {
    if (!session) return

    const allNoteIds = session.notes.map((note) => note.note_id)
    const totalNotes = allNoteIds.length
    const totalTasks = session.notes.reduce((sum, note) => sum + getPromptTypesForNote(note).length, 0)

    setProcessingAll(true)
    setError(null)
    setLastTimingBreakdown(null)
    const controller = new AbortController()
    abortControllerRef.current = controller

    setProgress({
      current: 0,
      total: totalTasks,
      currentNote: '',
      percentage: 0,
      timeRemaining: 0,
    })

    const startTime = Date.now()
    const processingTimes: number[] = []

    try {
      const updatedAnnotations = { ...session.annotations }
      let completedTasks = 0

      // Process notes one by one to show progress (each note processes prompts in parallel on backend)
      for (let i = 0; i < allNoteIds.length; i++) {
        if (controller.signal.aborted) break

        const noteId = allNoteIds[i]
        const note = session.notes[i]
        const noteStartTime = Date.now()

        setProgress({
          current: completedTasks,
          total: totalTasks,
          currentNote: `Note ${i + 1}/${totalNotes}: ${note.note_id}`,
          percentage: Math.round((completedTasks / totalTasks) * 100),
          timeRemaining: 0,
        })

        const notePromptTypes = getPromptTypesForNote(note)

        try {
          const result = await annotateApi.batchProcess(sessionId, {
            note_ids: [noteId],
            prompt_types: notePromptTypes,
            fewshot_k: 5,
            use_fewshots: true,
          }, controller.signal)

          if (result.results.length > 0) {
            if (!updatedAnnotations[noteId]) {
              updatedAnnotations[noteId] = {}
            }

            result.results[0].annotations.forEach((ann: AnnotationResult) => {
              updatedAnnotations[noteId][ann.prompt_type] = {
                note_id: noteId,
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
              }
            })

            completedTasks += notePromptTypes.length

            const noteTime = (Date.now() - noteStartTime) / 1000
            processingTimes.push(noteTime)
            const avgTimePerTask =
              processingTimes.reduce((a, b) => a + b, 0) / processingTimes.length / notePromptTypes.length
            const remainingTasks = totalTasks - completedTasks
            const estimatedTimeRemaining = Math.round(avgTimePerTask * remainingTasks)

            setProgress({
              current: completedTasks,
              total: totalTasks,
              currentNote: `Note ${i + 1}/${totalNotes}: ${note.note_id}`,
              percentage: Math.round((completedTasks / totalTasks) * 100),
              timeRemaining: estimatedTimeRemaining,
            })

            if (i % 5 === 0 || i === allNoteIds.length - 1) {
              const updatedSession = await sessionsApi.update(sessionId, updatedAnnotations)
              setSession(updatedSession)
            }
          }
        } catch (err: any) {
          if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') break
          console.error(`Failed to process note ${noteId}:`, err)
          completedTasks += notePromptTypes.length
        }
      }

      // Final update
      if (!controller.signal.aborted) {
        const updatedSession = await sessionsApi.update(sessionId, updatedAnnotations)
        setSession(updatedSession)
      }

      const totalTime = ((Date.now() - startTime) / 1000).toFixed(1)
      setProgress({
        current: controller.signal.aborted ? completedTasks : totalTasks,
        total: totalTasks,
        currentNote: controller.signal.aborted ? `Cancelled after ${totalTime}s` : `Complete! (${totalTime}s)`,
        percentage: Math.round((completedTasks / totalTasks) * 100),
        timeRemaining: 0,
      })
    } catch (err: any) {
      if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') {
        setError('Batch processing cancelled')
      } else {
        setError(err.response?.data?.detail || err.message || 'Batch processing failed')
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

  // Handle ICD-O-3 candidate selection
  const handleICDO3CandidateSelect = (noteId: string, promptType: string, icdo3Code: ICDO3CodeInfo) => {
    if (!session) return

    // Update local session state with the new ICD-O-3 code selection
    const updatedAnnotations = { ...session.annotations }
    if (updatedAnnotations[noteId]?.[promptType]) {
      updatedAnnotations[noteId][promptType] = {
        ...updatedAnnotations[noteId][promptType],
        icdo3_code: icdo3Code,
      }

      setSession({
        ...session,
        annotations: updatedAnnotations,
      })
    }
  }

  // Handle unified ICD-O-3 code save
  const handleUnifiedCodeSave = (noteId: string, unifiedCode: UnifiedICDO3Code) => {
    setUnifiedCodes(prev => ({
      ...prev,
      [noteId]: unifiedCode,
    }))
  }

  // Handle CSV export download
  const handleExport = async (mode: 'labels' | 'codes') => {
    setExporting(mode)
    try {
      const blob = mode === 'labels'
        ? await sessionsApi.exportLabels(sessionId)
        : await sessionsApi.exportCodes(sessionId)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = mode === 'labels'
        ? `${sessionId}_validated.csv`
        : `${sessionId}_coded.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || `Export failed`)
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
        <div className="flex justify-between items-center mb-4">
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
                    📊 Evaluation Mode
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
          <div className="flex gap-2">
            <button
              onClick={() => handleExport('labels')}
              disabled={exporting !== null}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm hover:bg-gray-50 disabled:opacity-50"
            >
              {exporting === 'labels' ? 'Exporting...' : 'Export Labels CSV'}
            </button>
            <button
              onClick={() => handleExport('codes')}
              disabled={exporting !== null}
              className="px-3 py-2 border border-indigo-300 text-indigo-700 rounded-md text-sm hover:bg-indigo-50 disabled:opacity-50"
            >
              {exporting === 'codes' ? 'Exporting...' : 'Export Codes CSV'}
            </button>
            <button
              onClick={() => setSelectedNoteIndex(Math.max(0, selectedNoteIndex - 1))}
              disabled={selectedNoteIndex === 0 || processingAll}
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
              disabled={selectedNoteIndex === session.notes.length - 1 || processingAll}
              className="px-4 py-2 border border-gray-300 rounded-md text-sm disabled:opacity-50"
            >
              Next
            </button>
          </div>
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
            <div className="flex gap-2">
              <button
                onClick={handleProcessAll}
                disabled={processingAll || session.notes.length === 0}
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
              {progress.timeRemaining > 0 && (
                <div className="text-xs text-gray-500 mt-1">
                  Estimated time remaining: {formatTimeRemaining(progress.timeRemaining)}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
          {error}
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
                disabled={processing || processingAll}
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
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs text-gray-600">
                {Object.entries(lastTimingBreakdown)
                  .filter(([k]) => k !== 'prompt_count')
                  .sort(([, a], [, b]) => b - a)
                  .map(([step, duration]) => (
                    <div key={step} className="flex justify-between">
                      <span className="text-gray-500">{step.replace(/_/g, ' ')}:</span>
                      <span className="font-mono font-medium">{duration.toFixed(2)}s</span>
                    </div>
                  ))}
              </div>
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
                // Extract expected annotation for this specific prompt type
                const expectedAnnotation = extractExpectedAnnotation(
                  currentNote.annotations || null,
                  promptType
                )

                // Build list of other annotations for this note (for unified ICD-O-3 code selection)
                const otherAnnotations: AnnotationResult[] = getPromptTypesForNote(currentNote)
                  .filter(pt => pt !== promptType && noteAnnotations[pt])
                  .map(pt => {
                    const ann = noteAnnotations[pt]
                    return {
                      prompt_type: ann.prompt_type,
                      annotation_text: ann.annotation_text,
                      values: ann.values || [],
                      evidence_spans: ann.evidence_spans || [],
                      reasoning: ann.reasoning,
                      is_negated: ann.is_negated,
                      date_info: ann.date_info,
                      evidence_text: ann.evidence_text,
                      raw_prompt: ann.raw_prompt,
                      raw_response: ann.raw_response,
                      status: ann.status,
                      evaluation_result: ann.evaluation_result,
                      icdo3_code: ann.icdo3_code,
                    }
                  })

                return (
                  <AnnotationViewer
                    key={promptType}
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
                            evaluation_result: annotation.evaluation_result,  // Include evaluation results
                            icdo3_code: annotation.icdo3_code,  // Include ICD-O-3 code information
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
                    onCandidateSelect={(icdo3Code) => handleICDO3CandidateSelect(currentNote.note_id, promptType, icdo3Code)}
                    otherAnnotations={otherAnnotations}
                    existingUnifiedCode={unifiedCodes[currentNote.note_id] || null}
                    onUnifiedCodeSave={(unifiedCode) => handleUnifiedCodeSave(currentNote.note_id, unifiedCode)}
                  />
                )
              })
            )}
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
    </div>
  )
}

