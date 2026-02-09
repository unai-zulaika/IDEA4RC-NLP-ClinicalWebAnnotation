'use client'

import { useState, useEffect, useMemo } from 'react'
import type { AnnotationResult, EvidenceSpan, AnnotationDateInfo, EntityMapping, EntityFieldMapping, PromptInfo, ICDO3CodeInfo, FieldEvaluation, FieldEvaluationResult, UnifiedICDO3Code } from '@/lib/api'
import { promptsApi, annotateApi } from '@/lib/api'
import UnifiedICDO3Selector from './UnifiedICDO3Selector'
import { isTemplateIncomplete, getPlaceholders } from '@/lib/annotationUtils'

type EvaluationViewMode = 'prompt' | 'field'

interface AnnotationDetailViewProps {
  annotation: AnnotationResult
  noteText: string
  expectedAnnotation?: string
  onClose: () => void
  onSelectSpan?: (span: EvidenceSpan) => void
  sessionId?: string
  noteId?: string
  onCandidateSelect?: (icdo3Code: ICDO3CodeInfo) => void
  // Props for unified ICD-O-3 selector
  otherAnnotations?: AnnotationResult[]  // Other annotations for the same note (to find histology/site pairs)
  existingUnifiedCode?: UnifiedICDO3Code | null
  onUnifiedCodeSave?: (unifiedCode: UnifiedICDO3Code) => void
}

export default function AnnotationDetailView({
  annotation,
  noteText,
  expectedAnnotation,
  onClose,
  onSelectSpan,
  sessionId,
  noteId,
  onCandidateSelect,
  otherAnnotations,
  existingUnifiedCode,
  onUnifiedCodeSave,
}: AnnotationDetailViewProps) {
  const [entityMapping, setEntityMapping] = useState<EntityMapping | null>(null)
  const [promptTemplate, setPromptTemplate] = useState<string>('')
  const [extractedMappings, setExtractedMappings] = useState<Record<string, string>>({})
  const [loadingMapping, setLoadingMapping] = useState(false)
  const [selectingCandidate, setSelectingCandidate] = useState(false)
  const [localIcdo3Code, setLocalIcdo3Code] = useState<ICDO3CodeInfo | undefined>(annotation.icdo3_code)
  const [evaluationViewMode, setEvaluationViewMode] = useState<EvaluationViewMode>('prompt')
  const [showUnifiedSelector, setShowUnifiedSelector] = useState(false)
  const [localUnifiedCode, setLocalUnifiedCode] = useState<UnifiedICDO3Code | null>(existingUnifiedCode || null)

  // Check if field-level evaluation is available
  const fieldEvaluation = annotation.evaluation_result?.field_evaluation
  const hasFieldEvaluation = fieldEvaluation?.field_evaluation_available === true

  // Helper to check if prompt type is histology-related
  const isHistologyPrompt = (promptType: string) => {
    const lower = promptType.toLowerCase()
    return lower.includes('histolog') || lower.includes('morpholog') || lower.includes('tipo')
  }

  // Helper to check if prompt type is topography/site-related
  // Be specific - only match 'site' or 'topograph', not general 'tumor' which matches too many prompts
  const isTopographyPrompt = (promptType: string) => {
    const lower = promptType.toLowerCase()
    // Match 'tumorsite' specifically, or 'site' or 'topograph' in general
    return (lower.includes('tumorsite') || lower.includes('topograph') ||
            (lower.includes('site') && !lower.includes('histolog')))
  }

  // Check if current annotation is an ICD-O-3 related prompt
  const currentIsHistology = isHistologyPrompt(annotation.prompt_type)
  const currentIsTopography = isTopographyPrompt(annotation.prompt_type)
  const isICDO3RelatedPrompt = currentIsHistology || currentIsTopography

  // Find paired annotation (histology for topography, or vice versa)
  const pairedAnnotation = useMemo(() => {
    if (!otherAnnotations || !isICDO3RelatedPrompt) return null

    if (currentIsHistology) {
      // Find topography annotation
      return otherAnnotations.find(a => isTopographyPrompt(a.prompt_type))
    } else if (currentIsTopography) {
      // Find histology annotation
      return otherAnnotations.find(a => isHistologyPrompt(a.prompt_type))
    }
    return null
  }, [otherAnnotations, currentIsHistology, currentIsTopography, isICDO3RelatedPrompt])

  // Extract morphology and topography codes
  const extractedCodes = useMemo(() => {
    let morphologyCode: string | undefined
    let topographyCode: string | undefined
    let morphologyDescription: string | undefined
    let topographyDescription: string | undefined

    // Get codes from current annotation
    if (currentIsHistology && localIcdo3Code) {
      morphologyCode = localIcdo3Code.morphology_code || localIcdo3Code.code
      morphologyDescription = localIcdo3Code.description
    } else if (currentIsTopography && localIcdo3Code) {
      topographyCode = localIcdo3Code.topography_code || localIcdo3Code.code
      topographyDescription = localIcdo3Code.description
    }

    // Get codes from paired annotation
    if (pairedAnnotation?.icdo3_code) {
      if (isHistologyPrompt(pairedAnnotation.prompt_type)) {
        morphologyCode = pairedAnnotation.icdo3_code.morphology_code || pairedAnnotation.icdo3_code.code
        morphologyDescription = pairedAnnotation.icdo3_code.description
      } else if (isTopographyPrompt(pairedAnnotation.prompt_type)) {
        topographyCode = pairedAnnotation.icdo3_code.topography_code || pairedAnnotation.icdo3_code.code
        topographyDescription = pairedAnnotation.icdo3_code.description
      }
    }

    return { morphologyCode, topographyCode, morphologyDescription, topographyDescription }
  }, [currentIsHistology, currentIsTopography, localIcdo3Code, pairedAnnotation])

  const hasBothCodes = Boolean(extractedCodes.morphologyCode && extractedCodes.topographyCode)

  // Handle unified code save
  const handleUnifiedCodeSave = (unifiedCode: UnifiedICDO3Code) => {
    setLocalUnifiedCode(unifiedCode)
    setShowUnifiedSelector(false)
    onUnifiedCodeSave?.(unifiedCode)
  }

  // Sync unified code state with prop
  useEffect(() => {
    setLocalUnifiedCode(existingUnifiedCode || null)
  }, [existingUnifiedCode])

  // Check if template is incomplete
  const templateIncomplete = isTemplateIncomplete(annotation.annotation_text)
  const placeholders = getPlaceholders(annotation.annotation_text)
  // Extract evidence text from annotation
  const evidenceText = annotation.evidence_spans.length > 0
    ? annotation.evidence_spans.map(span => span.text).join(' ')
    : annotation.evidence_text || 'No evidence spans available'

  // Sync local ICD-O-3 code state with annotation prop
  useEffect(() => {
    setLocalIcdo3Code(annotation.icdo3_code)
  }, [annotation.icdo3_code])

  // Handle ICD-O-3 candidate selection
  const handleSelectCandidate = async (index: number) => {
    if (!sessionId || !noteId || !localIcdo3Code) return

    setSelectingCandidate(true)
    try {
      const result = await annotateApi.selectICDO3Candidate(
        sessionId,
        noteId,
        annotation.prompt_type,
        index
      )

      if (result.success) {
        setLocalIcdo3Code(result.icdo3_code)
        onCandidateSelect?.(result.icdo3_code)
      }
    } catch (error) {
      console.error('Failed to select ICD-O-3 candidate:', error)
    } finally {
      setSelectingCandidate(false)
    }
  }

  // Load entity mapping and template for this prompt type
  useEffect(() => {
    const loadMapping = async () => {
      setLoadingMapping(true)
      try {
        const promptInfo: PromptInfo = await promptsApi.get(annotation.prompt_type)
        if (promptInfo.entity_mapping) {
          setEntityMapping(promptInfo.entity_mapping)
          setPromptTemplate(promptInfo.template)
          // Extract values from annotation text based on mapping and template
          extractMappingsFromAnnotation(annotation.annotation_text, promptInfo.entity_mapping, promptInfo.template)
        }
      } catch (error) {
        console.error('Failed to load entity mapping:', error)
      } finally {
        setLoadingMapping(false)
      }
    }
    loadMapping()
  }, [annotation.prompt_type, annotation.annotation_text])

  // Extract mappings from annotation text using template pattern
  const extractMappingsFromAnnotation = (annotationText: string, mapping: EntityMapping, template: string) => {
    if (!annotationText) {
      setExtractedMappings({})
      return
    }

    const extracted: Record<string, string> = {}

    // Extract main entity fact
    if (mapping.entity_type) {
      // Handle entity_type that might be "Entity.field" format or just "Entity"
      const entityParts = mapping.entity_type.split('.')
      const baseEntityType = entityParts[0]
      extracted['_entity_type'] = baseEntityType
      if (mapping.fact_trigger) {
        // Check if fact trigger is present in annotation
        const factPresent = annotationText.toLowerCase().includes(mapping.fact_trigger.toLowerCase())
        extracted['_fact_detected'] = factPresent ? 'Yes' : 'No'
      }
    }

    // Extract date from annotation if available
    if (annotation.date_info?.date_value) {
      extracted['_date'] = annotation.date_info.date_value
    }

    // Extract field mappings from placeholders using template pattern
    mapping.field_mappings.forEach((fieldMapping: EntityFieldMapping) => {
      const key = `${fieldMapping.entity_type}.${fieldMapping.field_name}`

      // Hardcoded value takes precedence
      if (fieldMapping.hardcoded_value != null && fieldMapping.hardcoded_value !== '') {
        extracted[key] = fieldMapping.hardcoded_value
        return
      }

      const placeholder = fieldMapping.template_placeholder
      if (placeholder === '[FULL_ANNOTATION]') {
        // Map entire annotation text
        extracted[key] = annotationText
      } else {
        // Strategy 1: Use template pattern to build regex
        // Find the output format line in template that contains the placeholder
        let value = ''
        
        // Find lines in template that contain the placeholder
        const templateLines = template.split('\n')
        let templatePattern = ''
        
        for (const line of templateLines) {
          if (line.includes(placeholder)) {
            templatePattern = line.trim()
            break
          }
        }
        
        // Also try to find in format instructions
        if (!templatePattern) {
          const formatMatch = template.match(/format[:\s]+(.*?)(?:\n|$)/i)
          if (formatMatch && formatMatch[1] && formatMatch[1].includes(placeholder)) {
            templatePattern = formatMatch[1].trim()
          }
        }
        
        if (templatePattern) {
          // Build regex from template pattern by replacing placeholder with capture group
          // Escape special regex characters but preserve the placeholder structure
          const escapedPattern = templatePattern
            .split(placeholder)
            .map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
            .join('(.+?)') // Replace placeholder with capture group
          
          // Try to match the pattern in annotation text
          try {
            const regex = new RegExp(escapedPattern, 'i')
            const match = annotationText.match(regex)
            if (match && match[1]) {
              value = match[1].trim()
              // Remove trailing period if present
              value = value.replace(/\.$/, '').trim()
            }
          } catch (e) {
            console.warn('Regex pattern error:', e, 'Pattern:', escapedPattern)
          }
        }
        
        // Strategy 2: If template pattern didn't work, try simple colon extraction
        if (!value || value === placeholder) {
          // For simple "Key: Value" format, extract value after colon
          const colonMatch = annotationText.match(/:\s*([^\n\.]+)/)
          if (colonMatch && colonMatch[1]) {
            value = colonMatch[1].trim().replace(/\.$/, '').trim()
          }
        }
        
        // Strategy 3: Extract based on placeholder-specific patterns
        if (!value || value === placeholder) {
          if (placeholder.includes('intention')) {
            const match = annotationText.match(/with\s+([^\s]+)\s+intention/i)
            if (match && match[1]) {
              value = match[1].trim()
            }
          } else if (placeholder.includes('where') || placeholder.includes('select where')) {
            const match = annotationText.match(/started\s+(?:at|in|on)?\s*([^\s]+(?:\s+[^\s]+)?)\s+on/i)
            if (match && match[1]) {
              value = match[1].trim()
            }
          } else if (placeholder.includes('date') || placeholder.includes('put date')) {
            // Look for date patterns (DD/MM/YYYY, DD-MM-YYYY, etc.)
            const dateMatch = annotationText.match(/on\s+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})/i)
            if (dateMatch && dateMatch[1]) {
              value = dateMatch[1].trim()
            }
          } else if (placeholder.includes('regimen')) {
            const match = annotationText.match(/utilized\s+([^\s]+(?:\s+[^\s]+)*)\s+regimen/i)
            if (match && match[1]) {
              value = match[1].trim()
            }
          } else if (placeholder.includes('reason')) {
            const match = annotationText.match(/because\s+of\s+([^\.]+)/i)
            if (match && match[1]) {
              value = match[1].trim()
            }
          }
        }

        // If still no value, check if placeholder is still present (incomplete annotation)
        if (!value && annotationText.includes(placeholder)) {
          value = '[Placeholder not filled]'
        } else if (!value) {
          value = '[Not extracted]'
        }

        extracted[key] = value
      }
    })

    setExtractedMappings(extracted)
  }

  const formatDateInfo = (dateInfo?: AnnotationDateInfo) => {
    if (!dateInfo) return null

    return (
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-600">Date:</span>
          <span className="text-xs text-gray-900">{dateInfo.date_value || 'Not specified'}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-600">Source:</span>
          <span className={`text-xs px-2 py-0.5 rounded ${
            dateInfo.source === 'extracted_from_text'
              ? 'bg-green-100 text-green-800'
              : 'bg-blue-100 text-blue-800'
          }`}>
            {dateInfo.source === 'extracted_from_text' ? 'Extracted from Text' : 'Derived from CSV'}
          </span>
        </div>
        {dateInfo.csv_date && dateInfo.source === 'derived_from_csv' && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-gray-600">CSV Date:</span>
            <span className="text-xs text-gray-700">{dateInfo.csv_date}</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex justify-between items-center p-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">
            Annotation Details: {annotation.prompt_type}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl font-bold"
          >
            ×
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Evaluation Results (only in evaluation mode) */}
          {annotation.evaluation_result && (
            <div className={`border-2 rounded-md p-4 ${
              annotation.evaluation_result.overall_match
                ? 'bg-green-50 border-green-300'
                : 'bg-red-50 border-red-300'
            }`}>
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">✓ Correctness Evaluation</h3>
                  <p className="text-xs text-gray-600">Compare expected vs predicted annotation</p>
                </div>
                {/* Toggle between prompt-level and field-level evaluation */}
                {hasFieldEvaluation && (
                  <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
                    <button
                      onClick={() => setEvaluationViewMode('prompt')}
                      className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                        evaluationViewMode === 'prompt'
                          ? 'bg-white text-gray-900 shadow-sm'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      Prompt Level
                    </button>
                    <button
                      onClick={() => setEvaluationViewMode('field')}
                      className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                        evaluationViewMode === 'field'
                          ? 'bg-white text-gray-900 shadow-sm'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      Per-Value
                    </button>
                  </div>
                )}
              </div>

              {/* Prompt-Level Evaluation View */}
              {evaluationViewMode === 'prompt' && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-700">Match Status:</span>
                    <span className={`text-xs px-3 py-1.5 rounded font-semibold ${
                      annotation.evaluation_result.overall_match
                        ? 'bg-green-200 text-green-900'
                        : 'bg-red-200 text-red-900'
                    }`}>
                      {annotation.evaluation_result.overall_match ? '✓ Match' : '✗ Mismatch'}
                    </span>
                    {annotation.evaluation_result.match_type && (
                      <span className="text-xs text-gray-500">
                        ({annotation.evaluation_result.match_type})
                      </span>
                    )}
                  </div>
                  {annotation.evaluation_result.similarity_score !== undefined && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-gray-600">Similarity Score:</span>
                      <span className="text-xs text-gray-900">
                        {annotation.evaluation_result.similarity_score.toFixed(4)}
                      </span>
                    </div>
                  )}
                  {annotation.evaluation_result.exact_match !== undefined && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-gray-600">Exact Match:</span>
                      <span className={`text-xs px-2 py-1 rounded ${
                        annotation.evaluation_result.exact_match
                          ? 'bg-green-100 text-green-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}>
                        {annotation.evaluation_result.exact_match ? 'Yes' : 'No'}
                      </span>
                    </div>
                  )}
                  {annotation.evaluation_result.expected_annotation !== undefined && (
                    <div className="mt-3 pt-3 border-t border-blue-200">
                      <span className="text-xs font-medium text-gray-600 block mb-1">Expected Annotation:</span>
                      <div className="bg-white border border-blue-200 rounded p-2 text-xs text-gray-900">
                        {annotation.evaluation_result.expected_annotation || '[NO EXPECTED ANNOTATION]'}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Field-Level Evaluation View */}
              {evaluationViewMode === 'field' && hasFieldEvaluation && fieldEvaluation && (
                <div className="space-y-3">
                  {/* Field-Level Summary */}
                  <div className="flex items-center gap-4 flex-wrap">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-gray-700">Field Match:</span>
                      <span className={`text-xs px-3 py-1.5 rounded font-semibold ${
                        fieldEvaluation.overall_field_match
                          ? 'bg-green-200 text-green-900'
                          : 'bg-red-200 text-red-900'
                      }`}>
                        {fieldEvaluation.fields_matched}/{fieldEvaluation.total_fields} fields
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-gray-600">Match Rate:</span>
                      <span className={`text-xs font-mono ${
                        (fieldEvaluation.field_match_rate ?? 0) >= 0.8 ? 'text-green-700' :
                        (fieldEvaluation.field_match_rate ?? 0) >= 0.5 ? 'text-yellow-700' : 'text-red-700'
                      }`}>
                        {((fieldEvaluation.field_match_rate ?? 0) * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>

                  {/* Field Results Table */}
                  {fieldEvaluation.field_results && fieldEvaluation.field_results.length > 0 && (
                    <div className="mt-3 border border-gray-200 rounded-md overflow-hidden">
                      <table className="min-w-full text-xs">
                        <thead className="bg-gray-50">
                          <tr>
                            <th className="text-left py-2 px-3 font-medium text-gray-700">Field</th>
                            <th className="text-left py-2 px-3 font-medium text-gray-700">Type</th>
                            <th className="text-left py-2 px-3 font-medium text-gray-700">Expected</th>
                            <th className="text-left py-2 px-3 font-medium text-gray-700">Predicted</th>
                            <th className="text-left py-2 px-3 font-medium text-gray-700">Result</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-200 bg-white">
                          {fieldEvaluation.field_results.map((field: FieldEvaluationResult, idx: number) => (
                            <tr key={idx} className={field.match ? 'bg-green-50' : 'bg-red-50'}>
                              <td className="py-2 px-3">
                                <span className="font-mono text-gray-800">{field.field_name}</span>
                              </td>
                              <td className="py-2 px-3">
                                <span className={`px-2 py-0.5 rounded text-xs ${
                                  field.field_type === 'date' ? 'bg-purple-100 text-purple-800' :
                                  field.field_type === 'categorical' ? 'bg-blue-100 text-blue-800' :
                                  'bg-gray-100 text-gray-800'
                                }`}>
                                  {field.field_type}
                                </span>
                              </td>
                              <td className="py-2 px-3">
                                <span className="font-mono text-gray-700">
                                  {field.expected || <em className="text-gray-400">empty</em>}
                                </span>
                              </td>
                              <td className="py-2 px-3">
                                <span className="font-mono text-gray-700">
                                  {field.predicted || <em className="text-gray-400">empty</em>}
                                </span>
                              </td>
                              <td className="py-2 px-3">
                                <div className="flex items-center gap-2">
                                  <span className={`font-semibold ${field.match ? 'text-green-700' : 'text-red-700'}`}>
                                    {field.match ? '✓' : '✗'}
                                  </span>
                                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                                    field.match_method === 'exact' ? 'bg-green-100 text-green-700' :
                                    field.match_method === 'date_normalized' ? 'bg-green-100 text-green-700' :
                                    field.match_method === 'semantic' ? 'bg-blue-100 text-blue-700' :
                                    field.match_method === 'extraction_success' ? 'bg-indigo-100 text-indigo-700' :
                                    field.match_method === 'extraction_failed' ? 'bg-red-100 text-red-700' :
                                    field.match_method === 'false_positive' ? 'bg-orange-100 text-orange-700' :
                                    field.match_method === 'both_placeholder' ? 'bg-gray-100 text-gray-700' :
                                    field.match_method === 'both_empty' ? 'bg-gray-100 text-gray-700' :
                                    'bg-gray-100 text-gray-600'
                                  }`}>
                                    {field.match_method.replace(/_/g, ' ')}
                                  </span>
                                </div>
                                {field.note && (
                                  <div className="mt-1 text-xs text-gray-500 italic">{field.note}</div>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Field-Level Feedback */}
                  <div className="mt-3 pt-3 border-t border-gray-200">
                    <div className="text-xs font-medium text-gray-600 mb-2">Feedback:</div>
                    <div className="space-y-1">
                      {fieldEvaluation.field_results?.filter((f: FieldEvaluationResult) => f.match).length! > 0 && (
                        <div className="flex items-start gap-2 text-xs text-green-700">
                          <span className="flex-shrink-0">✓</span>
                          <span>
                            Correct: {fieldEvaluation.field_results?.filter((f: FieldEvaluationResult) => f.match).map((f: FieldEvaluationResult) => f.field_name).join(', ')}
                          </span>
                        </div>
                      )}
                      {fieldEvaluation.field_results?.filter((f: FieldEvaluationResult) => !f.match).length! > 0 && (
                        <div className="flex items-start gap-2 text-xs text-red-700">
                          <span className="flex-shrink-0">✗</span>
                          <span>
                            Incorrect: {fieldEvaluation.field_results?.filter((f: FieldEvaluationResult) => !f.match).map((f: FieldEvaluationResult) => f.field_name).join(', ')}
                          </span>
                        </div>
                      )}
                      {fieldEvaluation.field_results?.some((f: FieldEvaluationResult) => f.match_method === 'extraction_success') && (
                        <div className="flex items-start gap-2 text-xs text-indigo-700">
                          <span className="flex-shrink-0">ℹ</span>
                          <span>
                            Values extracted where expected had placeholders: {
                              fieldEvaluation.field_results?.filter((f: FieldEvaluationResult) => f.match_method === 'extraction_success').map((f: FieldEvaluationResult) => f.field_name).join(', ')
                            }
                          </span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Expected Annotation (for reference) */}
                  {annotation.evaluation_result.expected_annotation !== undefined && (
                    <div className="mt-3 pt-3 border-t border-blue-200">
                      <span className="text-xs font-medium text-gray-600 block mb-1">Expected Annotation:</span>
                      <div className="bg-white border border-blue-200 rounded p-2 text-xs text-gray-900 font-mono">
                        {annotation.evaluation_result.expected_annotation || '[NO EXPECTED ANNOTATION]'}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* No field evaluation available message */}
              {evaluationViewMode === 'field' && !hasFieldEvaluation && (
                <div className="text-xs text-gray-500 italic p-3 bg-gray-50 rounded">
                  {fieldEvaluation?.reason || 'Field-level evaluation not available for this prompt type'}
                </div>
              )}
            </div>
          )}

          {/* Final Annotation */}
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-2">LLM Generated Annotation</h3>
            <div className="space-y-3">
              <div className={`bg-gray-50 border rounded-md p-3 text-sm text-gray-900 ${
                templateIncomplete 
                  ? 'border-yellow-400 bg-yellow-50' 
                  : 'border-gray-200'
              }`}>
                {annotation.annotation_text || 'No annotation text available'}
                {templateIncomplete && (
                  <div className="mt-2 pt-2 border-t border-yellow-300">
                    <div className="flex items-center gap-2 text-xs text-yellow-800">
                      <span className="font-semibold">⚠️ Template Incomplete:</span>
                      <span>The annotation contains placeholders indicating missing information.</span>
                    </div>
                    {placeholders.length > 0 && (
                      <div className="mt-1 text-xs text-yellow-700">
                        <span className="font-medium">Placeholders found:</span>{' '}
                        {placeholders.join(', ')}
                      </div>
                    )}
                  </div>
                )}
              </div>
              
              {/* Expected Annotation */}
              {expectedAnnotation && (
                <div>
                  <h4 className="text-xs font-medium text-gray-600 mb-1">Expected Annotation (from CSV)</h4>
                  <div className="bg-blue-50 border border-blue-200 rounded-md p-3 text-sm text-gray-900">
                    {expectedAnnotation}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Status */}
          {annotation.status && (
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Processing Status</h3>
              <div className={`inline-flex items-center gap-2 px-3 py-2 rounded-md ${
                annotation.status === 'error'
                  ? 'bg-red-100 text-red-800 border border-red-200'
                  : annotation.status === 'incomplete'
                  ? 'bg-yellow-100 text-yellow-800 border border-yellow-200'
                  : 'bg-blue-100 text-blue-800 border border-blue-200'
              }`}>
                <span className="text-sm font-medium">
                  {annotation.status === 'error' ? '❌ Parse Error' : annotation.status === 'incomplete' ? '⚠️ Incomplete' : '✓ Parsed'}
                </span>
                {annotation.status === 'incomplete' && (
                  <span className="text-xs">
                    (The reasoning or annotation may have been truncated)
                  </span>
                )}
                {annotation.status === 'success' && (
                  <span className="text-xs">
                    (Annotation was parsed successfully - this does not indicate correctness)
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Negation Status - only show when something is actually negated */}
          {annotation.is_negated === true && (
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Negation Status</h3>
              <div className="inline-flex items-center gap-2 px-3 py-2 rounded-md bg-red-100 text-red-800 border border-red-200">
                <span className="text-sm font-medium">
                  ⚠️ Negated
                </span>
                <span className="text-xs">
                  (This annotation indicates absence, negation, or negative finding)
                </span>
              </div>
            </div>
          )}

          {/* Evidence */}
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-2">Evidence</h3>
            <div className="bg-yellow-50 border border-yellow-200 rounded-md p-3">
              <div className="text-sm text-gray-900 mb-2 font-medium">
                Evidence Text ({annotation.evidence_spans.length} span{annotation.evidence_spans.length !== 1 ? 's' : ''}):
              </div>
              {annotation.evidence_spans.length > 0 ? (
                <div className="space-y-2">
                  {annotation.evidence_spans.map((span, idx) => (
                    <div
                      key={idx}
                      className="bg-white border border-yellow-300 rounded px-3 py-2 text-sm text-gray-800 cursor-pointer hover:bg-yellow-100"
                      onClick={() => onSelectSpan?.(span)}
                    >
                      <div className="font-medium text-xs text-gray-500 mb-1">
                        Span {idx + 1} (position {span.start}-{span.end})
                      </div>
                      <div>{span.text}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-gray-800">
                  {annotation.evidence_text ? (
                    <div className="bg-white border border-yellow-300 rounded px-3 py-2">
                      {annotation.evidence_text}
                    </div>
                  ) : (
                    <div className="text-gray-500 italic">No evidence spans or evidence text available</div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Reasoning - Always show if available */}
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-2">Reasoning Process</h3>
            <div className="bg-blue-50 border border-blue-200 rounded-md p-3">
              {annotation.reasoning ? (
                <div className="text-sm text-gray-800 whitespace-pre-wrap">
                  {annotation.reasoning}
                </div>
              ) : (
                <div className="text-sm text-gray-500 italic">No reasoning provided</div>
              )}
            </div>
          </div>

          {/* Date Information */}
          {annotation.date_info && (
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Date Information</h3>
              <div className="bg-purple-50 border border-purple-200 rounded-md p-3">
                {formatDateInfo(annotation.date_info)}
              </div>
            </div>
          )}

          {/* ICD-O-3 Code Information with Candidate Selection */}
          {(localIcdo3Code || (annotation.prompt_type && (annotation.prompt_type.includes('histolog') || (annotation.prompt_type.includes('site') && annotation.prompt_type.includes('tumor'))))) && (
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">ICD-O-3 Code Selection</h3>
              {localIcdo3Code ? (
              <div className="bg-indigo-50 border border-indigo-200 rounded-md p-3">
                {/* Candidate Selection UI */}
                {localIcdo3Code.candidates && localIcdo3Code.candidates.length > 0 ? (
                  <div className="space-y-3">
                    <p className="text-xs text-gray-600">
                      Select the most appropriate ICD-O-3 code from the candidates below (from CSV):
                    </p>

                    {/* Candidate List */}
                    <div className="space-y-2">
                      {localIcdo3Code.candidates.map((candidate, index) => (
                        <label
                          key={`${candidate.query_code}-${index}`}
                          className={`flex items-start gap-3 p-3 rounded-md border cursor-pointer transition-all ${
                            index === localIcdo3Code.selected_candidate_index
                              ? 'border-indigo-500 bg-indigo-100 ring-2 ring-indigo-300'
                              : 'border-gray-200 bg-white hover:bg-gray-50'
                          } ${selectingCandidate ? 'opacity-50 pointer-events-none' : ''}`}
                        >
                          <input
                            type="radio"
                            name="icdo3-candidate"
                            checked={index === localIcdo3Code.selected_candidate_index}
                            onChange={() => handleSelectCandidate(index)}
                            disabled={selectingCandidate || !sessionId || !noteId}
                            className="mt-1 h-4 w-4 text-indigo-600 border-gray-300 focus:ring-indigo-500"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-mono text-sm font-semibold text-indigo-800">
                                {candidate.query_code}
                              </span>
                              <span className={`text-xs px-2 py-0.5 rounded ${
                                candidate.match_score >= 0.8
                                  ? 'bg-green-100 text-green-800'
                                  : candidate.match_score >= 0.5
                                  ? 'bg-yellow-100 text-yellow-800'
                                  : 'bg-gray-100 text-gray-800'
                              }`}>
                                {(candidate.match_score * 100).toFixed(0)}% match
                              </span>
                              {index === localIcdo3Code.selected_candidate_index && localIcdo3Code.user_selected && (
                                <span className="text-xs px-2 py-0.5 rounded bg-blue-100 text-blue-800">
                                  ✓ Selected
                                </span>
                              )}
                            </div>
                            <div className="text-sm text-gray-700 mt-1 font-medium">
                              {candidate.name}
                            </div>
                            <div className="text-xs text-gray-500 mt-1">
                              Morphology: <span className="font-mono">{candidate.morphology_code || 'N/A'}</span>
                              {' | '}
                              Topography: <span className="font-mono">{candidate.topography_code || 'N/A'}</span>
                            </div>
                          </div>
                        </label>
                      ))}
                    </div>

                    {/* Selection status */}
                    {selectingCandidate && (
                      <div className="text-xs text-indigo-600 flex items-center gap-2">
                        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                        </svg>
                        Updating selection...
                      </div>
                    )}

                    {!sessionId && (
                      <div className="text-xs text-yellow-600">
                        Note: Selection is disabled (no session context)
                      </div>
                    )}

                    {/* Currently selected summary */}
                    <div className="mt-3 pt-3 border-t border-indigo-200">
                      <div className="text-xs font-semibold text-gray-700 mb-2">Currently Selected:</div>
                      <div className="bg-white rounded-md p-2 border border-indigo-200">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm font-bold text-indigo-800 bg-green-100 px-2 py-1 rounded border border-green-300">
                            {localIcdo3Code.query_code || localIcdo3Code.code}
                          </span>
                        </div>
                        {localIcdo3Code.description && (
                          <div className="text-xs text-gray-700 mt-1">
                            {localIcdo3Code.description}
                          </div>
                        )}
                        <div className="text-xs text-gray-500 mt-1">
                          {localIcdo3Code.morphology_code && (
                            <span>Morphology: <span className="font-mono">{localIcdo3Code.morphology_code}</span></span>
                          )}
                          {localIcdo3Code.morphology_code && localIcdo3Code.topography_code && ' | '}
                          {localIcdo3Code.topography_code && (
                            <span>Topography: <span className="font-mono">{localIcdo3Code.topography_code}</span></span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  /* Fallback: No candidates, show single code info */
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-gray-700">Code:</span>
                      <span className="text-xs text-gray-900 font-mono bg-green-100 px-2 py-1 rounded font-semibold border border-green-300">
                        {localIcdo3Code.query_code || localIcdo3Code.code}
                      </span>
                    </div>
                    {localIcdo3Code.description && (
                      <div className="mt-2">
                        <span className="text-xs font-medium text-gray-600 block mb-1">Label from CSV:</span>
                        <div className="text-xs text-gray-800 bg-white border border-indigo-200 rounded p-2">
                          {localIcdo3Code.description}
                        </div>
                      </div>
                    )}
                    {localIcdo3Code.morphology_code && (
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-gray-600">Morphology:</span>
                        <span className="text-xs text-gray-900 font-mono bg-white px-2 py-1 rounded">
                          {localIcdo3Code.morphology_code}
                        </span>
                      </div>
                    )}
                    {localIcdo3Code.topography_code && (
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-gray-600">Topography:</span>
                        <span className="text-xs text-gray-900 font-mono bg-white px-2 py-1 rounded">
                          {localIcdo3Code.topography_code}
                        </span>
                      </div>
                    )}
                    <div className="mt-2 pt-2 border-t border-indigo-200 text-xs text-yellow-700">
                      No candidates available. The code was extracted directly from text.
                    </div>
                  </div>
                )}

                {/* Unified Code Section - Show when both histology and topography are available */}
                {hasBothCodes && sessionId && noteId && (
                  <div className="mt-4 pt-4 border-t border-indigo-300">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-xs font-semibold text-indigo-800">
                        Unified Diagnosis Code
                      </div>
                      <button
                        onClick={() => setShowUnifiedSelector(true)}
                        className="text-xs px-3 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700"
                      >
                        {localUnifiedCode ? 'Edit Unified Code' : 'Create Unified Code'}
                      </button>
                    </div>
                    {localUnifiedCode ? (
                      <div className="bg-white rounded-md p-2 border border-indigo-200">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono text-sm font-bold text-indigo-900 bg-green-100 px-2 py-1 rounded border border-green-300">
                            {localUnifiedCode.query_code}
                          </span>
                          <span className="text-xs px-2 py-0.5 rounded bg-green-100 text-green-700">
                            Unified
                          </span>
                          {localUnifiedCode.user_selected && (
                            <span className="text-xs px-2 py-0.5 rounded bg-blue-100 text-blue-700">
                              User Selected
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-gray-700 mt-1">{localUnifiedCode.name}</div>
                        <div className="text-xs text-gray-500 mt-1">
                          Morphology: <span className="font-mono">{localUnifiedCode.morphology_code}</span>
                          {' | '}
                          Topography: <span className="font-mono">{localUnifiedCode.topography_code}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="text-xs text-gray-600">
                        Both histology ({extractedCodes.morphologyCode}) and topography ({extractedCodes.topographyCode}) codes are available.
                        Click the button above to validate and combine them into a unified diagnosis code.
                      </div>
                    )}
                  </div>
                )}
              </div>
              ) : (
                <div className="bg-yellow-50 border border-yellow-200 rounded-md p-3">
                  <div className="text-xs text-yellow-800">
                    <p className="font-medium mb-1">No ICD-O-3 code extracted</p>
                    <p className="text-yellow-700">
                      The system attempted to extract an ICD-O-3 code but none was found.
                      This may happen if:
                    </p>
                    <ul className="list-disc list-inside mt-1 text-yellow-700">
                      <li>The annotation contains a placeholder like "[select ICD-O-3 code]"</li>
                      <li>The extraction failed (check backend logs)</li>
                      <li>vLLM server is not available</li>
                      <li>CSV file is not accessible</li>
                    </ul>
                    <p className="text-yellow-700 mt-1">
                      Try reprocessing the note or check the backend logs for details.
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Unified ICD-O-3 Selector Modal */}
          {showUnifiedSelector && sessionId && noteId && (
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[60] p-4">
              <div className="max-w-2xl w-full max-h-[90vh] overflow-y-auto">
                <UnifiedICDO3Selector
                  sessionId={sessionId}
                  noteId={noteId}
                  morphologyCode={extractedCodes.morphologyCode}
                  topographyCode={extractedCodes.topographyCode}
                  morphologyDescription={extractedCodes.morphologyDescription}
                  topographyDescription={extractedCodes.topographyDescription}
                  existingUnifiedCode={localUnifiedCode}
                  onSave={handleUnifiedCodeSave}
                  onClose={() => setShowUnifiedSelector(false)}
                />
              </div>
            </div>
          )}

          {/* Extracted Entity Mappings */}
          {entityMapping && (
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Extracted Entity Mappings</h3>
              <div className="bg-green-50 border border-green-200 rounded-md p-3">
                {loadingMapping ? (
                  <div className="text-sm text-gray-500 italic">Loading mappings...</div>
                ) : (
                  <div className="space-y-3">
                    {/* Main Entity */}
                    {extractedMappings['_entity_type'] && (
                      <div className="bg-white border border-green-300 rounded-md p-3">
                        <div className="text-xs font-semibold text-gray-700 mb-2">Main Entity</div>
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-gray-600">Entity Type:</span>
                            <span className="text-xs text-gray-900 font-mono bg-gray-100 px-2 py-1 rounded">
                              {extractedMappings['_entity_type']}
                            </span>
                          </div>
                          {extractedMappings['_fact_detected'] && (
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-medium text-gray-600">Fact Detected:</span>
                              <span className={`text-xs px-2 py-1 rounded ${
                                extractedMappings['_fact_detected'] === 'Yes'
                                  ? 'bg-green-100 text-green-800'
                                  : 'bg-gray-100 text-gray-800'
                              }`}>
                                {extractedMappings['_fact_detected']}
                              </span>
                            </div>
                          )}
                          {entityMapping.fact_trigger && (
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-medium text-gray-600">Fact Trigger Pattern:</span>
                              <span className="text-xs text-gray-700 italic">"{entityMapping.fact_trigger}"</span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Field Mappings */}
                    {entityMapping.field_mappings.length > 0 && (
                      <div className="bg-white border border-green-300 rounded-md p-3">
                        <div className="text-xs font-semibold text-gray-700 mb-2">Field Mappings</div>
                        <div className="space-y-2">
                          {entityMapping.field_mappings.map((fieldMapping, idx) => {
                            const key = `${fieldMapping.entity_type}.${fieldMapping.field_name}`
                            const value = extractedMappings[key]
                            return (
                              <div key={idx} className="border-b border-green-200 last:border-b-0 pb-2 last:pb-0">
                                <div className="flex items-start gap-2">
                                  <div className="flex-1">
                                    <div className="text-xs font-medium text-gray-700 mb-1">
                                      {fieldMapping.entity_type}.{fieldMapping.field_name}
                                    </div>
                                    <div className="text-xs text-gray-600 mb-1">
                                      <span className="font-medium">From:</span>{' '}
                                      <span className="font-mono bg-gray-100 px-1 rounded">
                                        {fieldMapping.template_placeholder}
                                      </span>
                                    </div>
                                    <div className="text-xs text-gray-900 mt-1">
                                      <span className="font-medium">Value:</span>{' '}
                                      <span className={`font-mono px-2 py-1 rounded ${
                                        value && value !== '[Not extracted]' && value !== '[Placeholder not filled]'
                                          ? 'bg-green-100 text-green-900'
                                          : 'bg-yellow-100 text-yellow-900'
                                      }`}>
                                        {value || '[Not found]'}
                                      </span>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}

                    {/* Date Information */}
                    {extractedMappings['_date'] && (
                      <div className="bg-white border border-green-300 rounded-md p-3">
                        <div className="text-xs font-semibold text-gray-700 mb-2">Date</div>
                        <div className="text-xs text-gray-900">
                          <span className="font-mono bg-green-100 text-green-900 px-2 py-1 rounded">
                            {extractedMappings['_date']}
                          </span>
                        </div>
                      </div>
                    )}

                    {/* Summary Table */}
                    {(entityMapping.field_mappings.length > 0 || extractedMappings['_date']) && (
                      <div className="bg-white border border-green-300 rounded-md p-3">
                        <div className="text-xs font-semibold text-gray-700 mb-2">Extracted Values Summary</div>
                        <div className="overflow-x-auto">
                          <table className="min-w-full text-xs">
                            <thead>
                              <tr className="border-b border-gray-200">
                                <th className="text-left py-1 px-2 font-medium text-gray-700">Variable</th>
                                <th className="text-left py-1 px-2 font-medium text-gray-700">Value</th>
                                {extractedMappings['_date'] && (
                                  <th className="text-left py-1 px-2 font-medium text-gray-700">Date</th>
                                )}
                              </tr>
                            </thead>
                            <tbody>
                              {entityMapping.field_mappings.map((fieldMapping, idx) => {
                                const key = `${fieldMapping.entity_type}.${fieldMapping.field_name}`
                                const value = extractedMappings[key]
                                const hasValue = value && value !== '[Not extracted]' && value !== '[Placeholder not filled]'
                                return (
                                  <tr key={idx} className="border-b border-gray-100">
                                    <td className="py-1 px-2 font-mono text-gray-700">
                                      {fieldMapping.entity_type}.{fieldMapping.field_name}
                                    </td>
                                    <td className="py-1 px-2">
                                      <span className={`font-mono px-2 py-0.5 rounded ${
                                        hasValue
                                          ? 'bg-green-100 text-green-900'
                                          : 'bg-yellow-100 text-yellow-900'
                                      }`}>
                                        {value || '[Not found]'}
                                      </span>
                                    </td>
                                    {extractedMappings['_date'] && (
                                      <td className="py-1 px-2 font-mono text-gray-700">
                                        {extractedMappings['_date']}
                                      </td>
                                    )}
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {entityMapping.field_mappings.length === 0 && !extractedMappings['_entity_type'] && (
                      <div className="text-sm text-gray-500 italic">
                        No field mappings defined for this prompt type
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Values */}
          {annotation.values.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Extracted Values</h3>
              <div className="space-y-2">
                {annotation.values.map((value, idx) => (
                  <div key={idx} className="bg-gray-50 border border-gray-200 rounded-md p-2 text-sm">
                    <div className="font-medium text-gray-700">{value.value}</div>
                    {value.reasoning && (
                      <div className="text-xs text-gray-500 mt-1">{value.reasoning}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Raw Prompt and Response */}
          <div className="border-t border-gray-300 pt-4 mt-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Raw Prompt & Response</h3>
            <div className="space-y-4">
              {annotation.raw_prompt && (
                <div>
                  <h4 className="text-xs font-medium text-gray-600 mb-1">Prompt Sent to LLM:</h4>
                  <div className="bg-gray-900 text-gray-100 rounded-md p-3 text-xs font-mono overflow-x-auto max-h-60 overflow-y-auto">
                    <pre className="whitespace-pre-wrap">{annotation.raw_prompt}</pre>
                  </div>
                </div>
              )}
              {annotation.raw_response && (
                <div>
                  <h4 className="text-xs font-medium text-gray-600 mb-1">Raw LLM Response:</h4>
                  <div className="bg-gray-900 text-gray-100 rounded-md p-3 text-xs font-mono overflow-x-auto max-h-60 overflow-y-auto">
                    <pre className="whitespace-pre-wrap">{annotation.raw_response}</pre>
                  </div>
                </div>
              )}
              {!annotation.raw_prompt && !annotation.raw_response && (
                <div className="text-xs text-gray-500 italic">
                  Raw prompt and response not available
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-gray-200 p-4 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700 text-sm"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

