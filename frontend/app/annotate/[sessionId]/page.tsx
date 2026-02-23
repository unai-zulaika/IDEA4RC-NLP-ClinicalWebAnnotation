'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import { sessionsApi, annotateApi, promptsApi } from '@/lib/api'
import { useDefaultCenter } from '@/lib/useDefaultCenter'
import type { SessionData, AnnotationResult, EvidenceSpan, PromptInfo, ICDO3CodeInfo, UnifiedICDO3Code } from '@/lib/api'
import TextHighlighter from '@/components/TextHighlighter'
import AnnotationViewer from '@/components/AnnotationViewer'
import { extractExpectedAnnotation } from '@/lib/annotationUtils'

function ManagePromptTypesModal({
  session,
  availablePrompts,
  onClose,
  onSave,
  error,
}: {
  session: SessionData
  availablePrompts: PromptInfo[]
  onClose: () => void
  onSave: (reportTypeMapping: Record<string, string[]>) => Promise<void>
  error: string | null
}) {
  const allPromptTypes = availablePrompts.map((p) => p.prompt_type)
  const [saving, setSaving] = useState(false)

  // Report type mapping is the single source of truth for prompt selection
  const reportTypes = Array.from(new Set(session.notes.map((n) => n.report_type).filter(Boolean))).sort()
  const currentMapping = session.report_type_mapping || {}
  const [mapping, setMapping] = useState<Record<string, string[]>>(() => {
    const m: Record<string, string[]> = {}
    for (const rt of reportTypes) {
      // Default to current session prompt_types if no mapping exists for this report type
      m[rt] = currentMapping[rt] ? [...currentMapping[rt]] : [...session.prompt_types]
    }
    return m
  })

  const setMappingForRT = (rt: string, pts: string[]) => {
    setMapping((prev) => ({ ...prev, [rt]: pts }))
  }

  const selectAllForRT = (rt: string) => {
    setMappingForRT(rt, [...allPromptTypes])
  }

  const deselectAllForRT = (rt: string) => {
    setMappingForRT(rt, [])
  }

  // Apply the same change across all report types at once
  const selectAllGlobal = () => {
    const m: Record<string, string[]> = {}
    for (const rt of reportTypes) {
      m[rt] = [...allPromptTypes]
    }
    setMapping(m)
  }

  const deselectAllGlobal = () => {
    const m: Record<string, string[]> = {}
    for (const rt of reportTypes) {
      m[rt] = []
    }
    setMapping(m)
  }

  // Derive the effective prompt types from the mapping union
  const effectivePromptTypes = new Set<string>()
  for (const pts of Object.values(mapping)) {
    pts.forEach((pt) => effectivePromptTypes.add(pt))
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await onSave(mapping)
    } finally {
      setSaving(false)
    }
  }

  const hasChanges = (() => {
    for (const rt of reportTypes) {
      const prev = (currentMapping[rt] || session.prompt_types).slice().sort()
      const next = (mapping[rt] || []).slice().sort()
      if (prev.length !== next.length || prev.some((v, i) => v !== next[i])) return true
    }
    return false
  })()

  // Check which prompt types will be removed (have annotations that will be deleted)
  const removedTypes = session.prompt_types.filter((pt) => !effectivePromptTypes.has(pt))
  const removedWithAnnotations = removedTypes.filter((pt) =>
    Object.values(session.annotations).some((noteAnns) => pt in noteAnns)
  )

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full mx-4 max-h-[85vh] flex flex-col">
        <div className="p-6 border-b border-gray-200 flex justify-between items-center flex-shrink-0">
          <h2 className="text-xl font-bold text-gray-900">Manage Report Type → Prompt Mapping</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">
            ✕
          </button>
        </div>

        <div className="p-6 overflow-y-auto flex-1">
          <p className="text-xs text-gray-500 mb-3">
            Select which prompt types apply to each report type. The session&apos;s prompt types are determined by the union of all selections below.
          </p>

          {/* Global controls */}
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm text-gray-700">
              <strong>{effectivePromptTypes.size}</strong> prompt type{effectivePromptTypes.size !== 1 ? 's' : ''} active across {reportTypes.length} report type{reportTypes.length !== 1 ? 's' : ''}
            </span>
            <div className="flex gap-2">
              <button onClick={selectAllGlobal} className="text-xs text-blue-600 hover:text-blue-800 font-medium">Select All Everywhere</button>
              <button onClick={deselectAllGlobal} className="text-xs text-gray-500 hover:text-gray-700 font-medium">Clear All</button>
            </div>
          </div>

          {reportTypes.length > 0 ? (
            <div className="space-y-4">
              {reportTypes.map((rt) => {
                const selectedForRT = mapping[rt] || []
                return (
                  <div key={rt} className="border border-gray-200 rounded p-3">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-sm font-medium text-gray-800">{rt}</h4>
                      <div className="flex gap-2 items-center">
                        <span className="text-xs text-gray-500">{selectedForRT.length} selected</span>
                        <button onClick={() => selectAllForRT(rt)} className="text-xs text-blue-600 hover:text-blue-800">All</button>
                        <button onClick={() => deselectAllForRT(rt)} className="text-xs text-gray-500 hover:text-gray-700">None</button>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {allPromptTypes.map((pt) => {
                        const isOn = selectedForRT.includes(pt)
                        return (
                          <button
                            key={pt}
                            onClick={() => {
                              if (isOn) {
                                setMappingForRT(rt, selectedForRT.filter((x) => x !== pt))
                              } else {
                                setMappingForRT(rt, [...selectedForRT, pt])
                              }
                            }}
                            className={`text-xs px-2 py-1 rounded-full border transition-colors ${
                              isOn
                                ? 'bg-blue-100 border-blue-300 text-blue-800'
                                : 'bg-gray-50 border-gray-200 text-gray-500 hover:border-gray-300'
                            }`}
                          >
                            {pt}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-sm text-gray-500 border border-gray-200 rounded p-4 text-center">
              No report types found in this session&apos;s notes.
            </div>
          )}

          {/* Warning about annotation deletion */}
          {removedWithAnnotations.length > 0 && (
            <div className="mt-4 p-3 bg-amber-50 border border-amber-200 text-amber-800 rounded text-sm">
              Saving will remove <strong>{removedWithAnnotations.length}</strong> prompt type{removedWithAnnotations.length !== 1 ? 's' : ''} that have existing annotations: {removedWithAnnotations.join(', ')}. Their annotations will be deleted.
            </div>
          )}

          {error && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded text-sm">
              {error}
            </div>
          )}
        </div>

        {/* Footer with Save */}
        <div className="p-4 border-t border-gray-200 flex justify-end gap-3 flex-shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!hasChanges || saving}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

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
    return session.prompt_types
  }

  const handleProcessNote = async () => {
    if (!session) return

    const note = session.notes[selectedNoteIndex]
    if (!note) return

    const notePromptTypes = getPromptTypesForNote(note)
    const totalPrompts = notePromptTypes.length

    setProcessing(true)
    setError(null)
    setNoteProgress({
      current: 0,
      total: totalPrompts,
      currentPrompt: '',
      percentage: 0,
    })

    try {
      const updatedAnnotations = { ...session.annotations }
      if (!updatedAnnotations[note.note_id]) {
        updatedAnnotations[note.note_id] = {}
      }

      // Process each prompt type sequentially to show progress
      for (let i = 0; i < notePromptTypes.length; i++) {
        const promptType = notePromptTypes[i]
        
        setNoteProgress({
          current: i,
          total: totalPrompts,
          currentPrompt: promptType,
          percentage: Math.round((i / totalPrompts) * 100),
        })

        try {
          const result = await annotateApi.batchProcess(sessionId, {
            note_ids: [note.note_id],
            prompt_types: [promptType],
            fewshot_k: 5,
            use_fewshots: true,
          })

          if (result.results.length > 0 && result.results[0].annotations.length > 0) {
            const ann = result.results[0].annotations[0]
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
              evaluation_result: ann.evaluation_result,  // Preserve evaluation results
              icdo3_code: ann.icdo3_code,  // Preserve ICD-O-3 code information
            }
          }
        } catch (err: any) {
          console.error(`Failed to process ${promptType}:`, err)
          // Continue with next prompt type
        }
      }

      // Final update
      setNoteProgress({
        current: totalPrompts,
        total: totalPrompts,
        currentPrompt: 'Complete!',
        percentage: 100,
      })

      const updatedSession = await sessionsApi.update(sessionId, updatedAnnotations)
      setSession(updatedSession)

      // Clear progress after a short delay
      setTimeout(() => {
        setNoteProgress({
          current: 0,
          total: 0,
          currentPrompt: '',
          percentage: 0,
        })
      }, 1000)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Processing failed')
    } finally {
      setProcessing(false)
    }
  }

  const handleProcessAll = async () => {
    if (!session) return

    const allNoteIds = session.notes.map((note) => note.note_id)
    const totalNotes = allNoteIds.length
    const totalTasks = session.notes.reduce((sum, note) => sum + getPromptTypesForNote(note).length, 0)

    setProcessingAll(true)
    setError(null)
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

      // Process notes one by one to show progress
      for (let i = 0; i < allNoteIds.length; i++) {
        const noteId = allNoteIds[i]
        const note = session.notes[i]
        const noteStartTime = Date.now()

        setProgress({
          current: completedTasks,
          total: totalTasks,
          currentNote: `Note ${i + 1}/${totalNotes}: ${note.note_id}`,
          percentage: Math.round((completedTasks / totalTasks) * 100),
          timeRemaining: 0, // Will calculate after first note
        })

        const notePromptTypes = getPromptTypesForNote(note)

        try {
          const result = await annotateApi.batchProcess(sessionId, {
            note_ids: [noteId],
            prompt_types: notePromptTypes,
            fewshot_k: 5,
            use_fewshots: true,
          })

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
                evaluation_result: ann.evaluation_result,  // Preserve evaluation results
                icdo3_code: ann.icdo3_code,  // Preserve ICD-O-3 code information
              }
            })

            completedTasks += notePromptTypes.length

            // Calculate average time per task and estimate remaining
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

            // Update session periodically (every 5 notes or at the end)
            if (i % 5 === 0 || i === allNoteIds.length - 1) {
              const updatedSession = await sessionsApi.update(sessionId, updatedAnnotations)
              setSession(updatedSession)
            }
          }
        } catch (err: any) {
          console.error(`Failed to process note ${noteId}:`, err)
          // Continue with next note
          completedTasks += notePromptTypes.length
        }
      }

      // Final update
      const updatedSession = await sessionsApi.update(sessionId, updatedAnnotations)
      setSession(updatedSession)

      const totalTime = ((Date.now() - startTime) / 1000).toFixed(1)
      setProgress({
        current: totalTasks,
        total: totalTasks,
        currentNote: 'Complete!',
        percentage: 100,
        timeRemaining: 0,
      })
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Batch processing failed')
    } finally {
      setProcessingAll(false)
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
            <button
              onClick={handleProcessAll}
              disabled={processingAll || session.notes.length === 0}
              className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
            >
              {processingAll ? 'Processing...' : 'Process All Notes'}
            </button>
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
            <button
              onClick={handleProcessNote}
              disabled={processing || processingAll}
              className="px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
            >
              {processing ? 'Processing...' : 'Process Note'}
            </button>
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

