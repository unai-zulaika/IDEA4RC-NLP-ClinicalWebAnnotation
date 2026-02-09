'use client'

import { useState } from 'react'
import { useForm, useFieldArray } from 'react-hook-form'
import type { AnnotationResult, EvidenceSpan, ICDO3CodeInfo, UnifiedICDO3Code } from '@/lib/api'
import AnnotationDetailView from './AnnotationDetailView'
import { getColorClassesForPromptType, getColorForPromptType } from '@/lib/colors'
import { isTemplateIncomplete } from '@/lib/annotationUtils'

interface AnnotationViewerProps {
  annotation: AnnotationResult
  expectedAnnotation?: string
  noteText?: string
  onSave?: (values: string[]) => void
  onSelectSpan?: (span: EvidenceSpan) => void
  sessionId?: string
  noteId?: string
  onCandidateSelect?: (icdo3Code: ICDO3CodeInfo) => void
  // Props for unified ICD-O-3 selector
  otherAnnotations?: AnnotationResult[]
  existingUnifiedCode?: UnifiedICDO3Code | null
  onUnifiedCodeSave?: (unifiedCode: UnifiedICDO3Code) => void
}

interface FormValues {
  values: Array<{ value: string }>
}

export default function AnnotationViewer({
  annotation,
  expectedAnnotation,
  noteText = '',
  onSave,
  onSelectSpan,
  sessionId,
  noteId,
  onCandidateSelect,
  otherAnnotations,
  existingUnifiedCode,
  onUnifiedCodeSave,
}: AnnotationViewerProps) {
  const [showReasoning, setShowReasoning] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [showDetailView, setShowDetailView] = useState(false)

  const { register, control, handleSubmit, watch, reset } = useForm<FormValues>({
    defaultValues: {
      // Always use annotation_text as the primary value for editing
      // If values exist and are different, include them as additional editable fields
      values:
        annotation.annotation_text
          ? [{ value: annotation.annotation_text }, ...(annotation.values || []).filter(v => v.value && v.value !== annotation.annotation_text).map((v) => ({ value: v.value }))]
          : annotation.values.length > 0
          ? annotation.values.map((v) => ({ value: v.value }))
          : [{ value: '' }],
    },
  })

  const { fields, append, remove } = useFieldArray({
    control,
    name: 'values',
  })

  const onSubmit = (data: FormValues) => {
    const values = data.values.map((v) => v.value).filter((v) => v.trim() !== '')
    onSave?.(values)
    setIsEditing(false)
  }

  const handleEdit = () => {
    setIsEditing(true)
  }

  const handleCancel = () => {
    reset()
    setIsEditing(false)
  }

  const currentValues = watch('values')
  const colorClasses = getColorClassesForPromptType(annotation.prompt_type)
  const titleColor = getColorForPromptType(annotation.prompt_type)
  
  // Check if annotation has been processed (has annotation text or status)
  const isProcessed = !!(annotation.annotation_text || annotation.status || annotation.raw_response)
  const templateIncomplete = isProcessed && isTemplateIncomplete(annotation.annotation_text)

  return (
    <>
      <div className={`border-2 ${colorClasses.border} rounded-lg p-4 space-y-4 ${isProcessed ? 'hover:shadow-md transition-shadow cursor-pointer' : ''} bg-white`} onClick={() => isProcessed && setShowDetailView(true)}>
        <div className="flex justify-between items-start">
          <div className="flex-1">
            <h3 className="text-sm font-semibold" style={{ color: titleColor }}>
              {annotation.prompt_type}
            </h3>
            {annotation.confidence_score !== undefined && (
              <p className="text-xs text-gray-500 mt-1">
                Confidence: {annotation.confidence_score.toFixed(3)}
              </p>
            )}
            
            {/* Show "Not Processed" message if annotation hasn't been processed */}
            {!isProcessed && (
              <div className="mt-3 p-3 bg-gray-50 border border-gray-200 rounded-md">
                <p className="text-sm text-gray-600 italic">
                  ⏳ This note has not been processed yet. Click "Process Note" to generate annotations.
                </p>
              </div>
            )}
            
            {/* Quick indicators - only show if processed */}
            {isProcessed && (
              <div className="flex gap-2 mt-2 flex-wrap">
                {/* Evaluation result badge (only in evaluation mode) - shows correctness */}
                {annotation.evaluation_result && (
                  <>
                    <span className={`text-xs px-2.5 py-1 rounded font-semibold border ${
                      annotation.evaluation_result.overall_match
                        ? 'bg-green-200 text-green-900 border-green-300'
                        : 'bg-red-200 text-red-900 border-red-300'
                    }`}>
                      {annotation.evaluation_result.overall_match ? '✓ Match' : '✗ Mismatch'}
                    </span>
                    {/* Field-level evaluation indicator */}
                    {annotation.evaluation_result.field_evaluation?.field_evaluation_available && (
                      <span className={`text-xs px-2 py-0.5 rounded font-medium border ${
                        annotation.evaluation_result.field_evaluation.overall_field_match
                          ? 'bg-indigo-100 text-indigo-800 border-indigo-200'
                          : 'bg-orange-100 text-orange-800 border-orange-200'
                      }`} title="Per-value evaluation available">
                        📊 {annotation.evaluation_result.field_evaluation.fields_matched}/{annotation.evaluation_result.field_evaluation.total_fields} fields
                      </span>
                    )}
                  </>
                )}
                {annotation.status && (
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                    annotation.status === 'error'
                      ? 'bg-red-100 text-red-800'
                      : annotation.status === 'incomplete'
                      ? 'bg-yellow-100 text-yellow-800'
                      : 'bg-blue-100 text-blue-800'
                  }`}>
                    {annotation.status === 'error' ? '❌ Parse Error' : annotation.status === 'incomplete' ? '⚠️ Incomplete' : '✓ Parsed'}
                  </span>
                )}
                {/* Only show negation badge when something is actually negated */}
                {annotation.is_negated === true && (
                  <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-800">
                    ⚠️ Negated
                  </span>
                )}
                {annotation.date_info && (
                  <span className="text-xs px-2 py-0.5 rounded bg-purple-100 text-purple-800">
                    📅 {annotation.date_info.date_value || 'Date info'}
                  </span>
                )}
                {annotation.evidence_spans.length > 0 && (
                  <span className="text-xs px-2 py-0.5 rounded bg-yellow-100 text-yellow-800">
                    🔍 {annotation.evidence_spans.length} evidence span{annotation.evidence_spans.length !== 1 ? 's' : ''}
                  </span>
                )}
                {templateIncomplete && (
                  <span className="text-xs px-2 py-0.5 rounded bg-orange-100 text-orange-800 font-medium">
                    ⚠️ Template Incomplete
                  </span>
                )}
              </div>
            )}
          </div>
          {!isEditing && isProcessed && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                handleEdit()
              }}
              className="text-sm text-primary-600 hover:text-primary-700"
            >
              Edit
            </button>
          )}
        </div>

      {/* Only show expected annotation if note has been processed */}
      {isProcessed && expectedAnnotation && expectedAnnotation !== annotation.annotation_text && (
        <div className="bg-yellow-50 border border-yellow-200 rounded p-2">
          <p className="text-xs font-medium text-yellow-800 mb-1">Expected:</p>
          <p className="text-xs text-yellow-700">{expectedAnnotation}</p>
        </div>
      )}

      {isEditing ? (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
          {fields.map((field, index) => (
            <div key={field.id} className="flex gap-2">
              <input
                {...register(`values.${index}.value` as const)}
                className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder="Enter value"
              />
              {fields.length > 1 && (
                <button
                  type="button"
                  onClick={() => remove(index)}
                  className="px-3 py-2 text-red-600 hover:text-red-700 text-sm"
                >
                  Remove
                </button>
              )}
            </div>
          ))}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => append({ value: '' })}
              className="text-sm text-primary-600 hover:text-primary-700"
            >
              + Add Value
            </button>
            <div className="flex-1" />
            <button
              type="button"
              onClick={handleCancel}
              className="px-3 py-1.5 text-sm text-gray-700 hover:text-gray-900"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-3 py-1.5 bg-primary-600 text-white text-sm rounded-md hover:bg-primary-700"
            >
              Save
            </button>
          </div>
        </form>
      ) : isProcessed ? (
        <div className="space-y-2">
          {/* Always show the actual annotation_text from the model (the LLM's output) */}
          <div className="px-3 py-2 bg-gray-50 rounded-md text-sm text-gray-900">
            {annotation.annotation_text || 'No annotation generated'}
          </div>
        </div>
      ) : null}

      {isProcessed && annotation.evidence_spans.length > 0 && (
        <div>
          <button
            onClick={() => setShowReasoning(!showReasoning)}
            className="text-xs text-gray-500 hover:text-gray-700 mb-2"
          >
            {showReasoning ? '▼' : '▶'} Evidence Spans ({annotation.evidence_spans.length})
          </button>
          {showReasoning && (
            <div className="space-y-1 mt-2">
              {annotation.evidence_spans.map((span, idx) => (
                <div
                  key={idx}
                  className="text-xs px-2 py-1 bg-blue-50 rounded cursor-pointer hover:bg-blue-100"
                  onClick={() => onSelectSpan?.(span)}
                >
                  <span className="font-medium">{span.prompt_type}:</span>{' '}
                  {span.text.substring(0, 100)}
                  {span.text.length > 100 ? '...' : ''}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {isProcessed && annotation.reasoning && (
        <div>
          <button
            onClick={() => setShowReasoning(!showReasoning)}
            className="text-xs text-gray-500 hover:text-gray-700 mb-2"
          >
            {showReasoning ? '▼' : '▶'} Why?
          </button>
          {showReasoning && (
            <div className="mt-2 px-3 py-2 bg-gray-50 rounded-md text-xs text-gray-700">
              {annotation.reasoning}
            </div>
          )}
        </div>
      )}

      {/* Click hint - only show if processed */}
      {isProcessed && (
        <div className="text-xs text-gray-400 italic mt-2">
          Click to view detailed annotation information
        </div>
      )}
    </div>

    {/* Detail View Modal - only show if processed */}
    {showDetailView && noteText && isProcessed && (
      <AnnotationDetailView
        annotation={annotation}
        noteText={noteText}
        expectedAnnotation={expectedAnnotation}
        onClose={() => setShowDetailView(false)}
        onSelectSpan={onSelectSpan}
        sessionId={sessionId}
        noteId={noteId}
        onCandidateSelect={onCandidateSelect}
        otherAnnotations={otherAnnotations}
        existingUnifiedCode={existingUnifiedCode}
        onUnifiedCodeSave={onUnifiedCodeSave}
      />
    )}
    </>
  )
}

