/**
 * API Client for Clinical Data Curation Platform
 */

import axios from 'axios'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 180_000, // 3 minutes default
  headers: {
    'Content-Type': 'application/json',
  },
})

// Retry interceptor for 502/503/504 errors (2 retries with exponential backoff)
api.interceptors.response.use(undefined, async (error) => {
  const config = error.config
  if (!config || config.__retryCount >= 2) return Promise.reject(error)
  const status = error.response?.status
  if (status === 502 || status === 503 || status === 504) {
    config.__retryCount = (config.__retryCount || 0) + 1
    const delay = 1000 * Math.pow(2, config.__retryCount - 1) // 1s, 2s
    await new Promise((r) => setTimeout(r, delay))
    return api(config)
  }
  return Promise.reject(error)
})

// Helpers
function parseExcludedRowsHeader(header: string | undefined): ExcludedRow[] {
  if (!header) return []
  try {
    return JSON.parse(header) as ExcludedRow[]
  } catch {
    return []
  }
}

// Types
export interface ServerStatus {
  status: string
  model_name?: string
  endpoint?: string
}

export interface ServerMetrics {
  gpu_memory_used_gb?: number
  gpu_memory_total_gb?: number
  gpu_utilization_percent?: number
  throughput_tokens_per_sec?: number
  throughput_requests_per_sec?: number
  active_requests?: number
}

export interface ModelInfo {
  id: string
  name: string
  is_active: boolean
}

export interface OutputWordMapping {
  pattern: string   // Python re.search() regex tested against LLM final_output
  value: string     // Value to store for this field if pattern matches
  flags?: string    // Comma-separated: "IGNORECASE", "MULTILINE"
}

export interface EntityFieldMapping {
  template_placeholder: string
  entity_type: string
  field_name: string
  hardcoded_value?: string
  value_code_mappings?: Record<string, string>
  output_word_mappings?: OutputWordMapping[]
}

export interface EntityMapping {
  entity_type: string
  fact_trigger?: string
  field_mappings: EntityFieldMapping[]
}

export type PromptMode = 'standard' | 'fast'

export interface PromptInfo {
  prompt_type: string
  template: string
  report_types?: string[]
  entity_mapping?: EntityMapping
  center?: string
}

export interface CSVRow {
  text: string
  date: string
  p_id: string
  note_id: string
  report_type: string
  annotations?: string
}

export interface ExcludedRow {
  patient_id: string
  variable: string
  value: string
  reason: string
}

export interface ConflictSource {
  value: string
  note_id: string
  prompt_type: string
}

export interface ExportConflict {
  patient_id: string
  core_variable: string
  date_ref: string | null
  conflicting_values: string[]
  conflict_type: 'non_repeatable' | 'repeatable_same_date'
  sources: ConflictSource[]
}

export interface ExportValidationResponse {
  valid: boolean
  conflicts: ExportConflict[]
  row_count: number
  deduplicated_count: number
}

export interface ConflictResolveEntry {
  note_id: string
  prompt_type: string
}

export interface ConflictResolveResponse {
  deleted_count: number
  not_found_count: number
  remaining_conflicts: ExportConflict[]
  valid: boolean
  row_count: number
}

export interface CSVUploadResponse {
  success: boolean
  message: string
  row_count: number
  columns: string[]
  preview: Record<string, any>[]  // First 10 rows for display
  all_rows: Record<string, any>[]  // All rows for session creation
  session_id?: string  // Deprecated - no longer used
  has_annotations?: boolean  // True if annotations column exists and has values
  report_types?: string[]  // Unique report types found in CSV
  duplicate_note_ids_detected?: boolean  // True if duplicate note_ids were found and deduplicated
  duplicate_text_detected?: boolean  // True if rows with duplicate text content were removed
  duplicate_text_removed_count?: number  // Number of rows removed due to duplicate text
  duplicate_text_note_ids?: string[]  // note_ids of the removed rows
}

export interface EvidenceSpan {
  start: number
  end: number
  text: string
  prompt_type: string
}

export interface AnnotationValue {
  value: string
  evidence_spans: EvidenceSpan[]
  reasoning?: string
}

export interface AnnotationDateInfo {
  date_value?: string
  source: 'extracted_from_text' | 'derived_from_csv'
  csv_date?: string
}

export interface FieldEvaluationResult {
  field_name: string
  placeholder: string
  field_type: 'date' | 'categorical' | 'text'
  expected: string
  predicted: string
  match: boolean
  match_method: string  // 'exact', 'date_normalized', 'semantic', 'high_similarity', 'extraction_success', 'extraction_failed', etc.
  similarity: number
  note?: string
}

export interface FieldEvaluation {
  field_evaluation_available: boolean
  reason?: string
  template_format?: string
  total_fields?: number
  fields_matched?: number
  field_match_rate?: number
  overall_field_match?: boolean
  field_results?: FieldEvaluationResult[]
}

export interface EvaluationResult {
  // Prompt-level evaluation
  exact_match?: boolean
  similarity_score?: number
  high_similarity?: boolean
  overall_match?: boolean
  expected_annotation?: string
  predicted_annotation?: string
  match_type?: string  // 'match', 'mismatch', 'both_empty', 'false_positive', 'false_negative'
  total_values?: number
  values_matched?: number
  value_match_rate?: number
  value_details?: any[]
  // Field-level evaluation (per-value)
  field_evaluation?: FieldEvaluation
  merged_dates?: string[]  // Merged dates from template and extraction
}

export interface ICDO3CodeCandidate {
  rank: number  // Position in candidate list (1-5)
  query_code: string  // Full query code from CSV (e.g., "8940/0-C00.2")
  morphology_code?: string  // Morphology code (e.g., "8940/0")
  topography_code?: string  // Topography code (e.g., "C00.2")
  name: string  // NAME column from CSV - the label shown to user
  match_score: number  // Similarity/relevance score (0.0-1.0)
  match_method: string  // How this candidate was found
}

export interface ICDO3CodeInfo {
  code: string  // Currently selected ICD-O-3 code (e.g., "8805/3" or "8805/3-C71.7")
  topography_code?: string  // Topography code (e.g., "C71.7")
  morphology_code?: string  // Morphology code (e.g., "8805/3")
  histology_code?: string  // Histology code (e.g., "8805")
  behavior_code?: string  // Behavior code (e.g., "3")
  description?: string  // Description of the code
  confidence?: number  // Confidence score if available
  query_code?: string  // Query code from CSV (e.g., "8940/0-C00.2")
  match_method?: string  // How the code was matched ("exact", "llm_csv", "pattern", etc.)
  match_score?: number  // Match confidence score (0.0-1.0)
  // Multi-candidate support
  candidates?: ICDO3CodeCandidate[]  // Top 5 candidates from CSV
  selected_candidate_index?: number  // Which candidate is currently selected (0-4)
  user_selected?: boolean  // True if user manually selected a candidate
}

// Unified ICD-O-3 Code Types (for combined histology + topography)
export interface ICDO3SearchResult {
  query_code: string  // Full query code (e.g., "8031/3-C00.2")
  morphology_code: string  // Morphology code (e.g., "8031/3")
  topography_code: string  // Topography code (e.g., "C00.2")
  name: string  // Description from CSV NAME column
  match_score: number  // Relevance score (0.0-1.0)
}

export interface ICDO3SearchResponse {
  results: ICDO3SearchResult[]
  total_count: number
  query: string
  morphology_filter?: string
  topography_filter?: string
}

export interface ICDO3ValidationResult {
  valid: boolean  // Whether the combination exists in CSV
  query_code?: string  // Full query code if valid
  name?: string  // Description if valid
  morphology_valid: boolean  // Whether morphology code exists
  topography_valid: boolean  // Whether topography code exists
}

export interface UnifiedICDO3Code {
  query_code: string  // Full code (e.g., "8031/3-C00.2")
  morphology_code: string  // Morphology/histology code
  topography_code: string  // Topography/site code
  name: string  // Description from CSV
  source: string  // "combined", "user_override", "search_selected"
  user_selected: boolean
  validation: Record<string, boolean>
  created_at?: string
}

export interface ICDO3CombineResponse {
  success: boolean
  unified_code?: UnifiedICDO3Code
  message?: string
}

// Patient-level diagnosis resolution
export interface PatientDiagnosisCode {
  code: string
  note_id: string
  description?: string
  prompt_type?: string
}

export interface PatientDiagnosisInfo {
  patient_id: string
  status: 'auto_resolved' | 'needs_review' | 'manually_resolved' | 'skipped'
  review_reasons: string[]
  histology_codes: PatientDiagnosisCode[]
  topography_codes: PatientDiagnosisCode[]
  resolved_code?: UnifiedICDO3Code | null
  csv_id?: string | null
  resolved_at?: string
  resolved_by?: string
}

export interface DiagnosisValidationReport {
  patients: PatientDiagnosisInfo[]
  total_patients: number
  auto_resolved: number
  needs_review: number
  manually_resolved: number
  skipped: number
}

export interface PatientDiagnosisResolveResponse {
  success: boolean
  diagnosis?: PatientDiagnosisInfo
  message?: string
}

export interface ICDO3TopographiesResponse {
  morphology: string
  topographies: Array<{
    topography_code: string
    query_code: string
    name: string
  }>
  count: number
}

export interface ICDO3MorphologiesResponse {
  topography: string
  morphologies: Array<{
    morphology_code: string
    query_code: string
    name: string
  }>
  count: number
}

export interface ICDO3UnifiedCodeResponse {
  note_id: string
  unified_code: UnifiedICDO3Code | null
  exists: boolean
}

export interface HallucinationFlag {
  type: string
  field: string
  severity: 'medium' | 'high'
  duplicate_ratio: number
  message: string
}

export interface AnnotationResult {
  prompt_type: string
  annotation_text: string
  values: AnnotationValue[]
  confidence_score?: number
  evidence_spans: EvidenceSpan[]
  reasoning?: string
  is_negated?: boolean
  date_info?: AnnotationDateInfo
  evidence_text?: string  // Raw evidence text from structured annotation
  raw_prompt?: string  // Raw prompt sent to LLM
  raw_response?: string  // Raw response from LLM
  status?: 'success' | 'error' | 'incomplete'  // Annotation status
  evaluation_result?: EvaluationResult  // Evaluation metrics (only in evaluation mode)
  icdo3_code?: ICDO3CodeInfo  // ICD-O-3 code information (for histology/site prompts)
  timing_breakdown?: Record<string, number>  // Per-step timing breakdown
  derived_field_values?: Record<string, string>  // Values resolved via output_word_mappings at annotation time
  hallucination_flags?: HallucinationFlag[]  // Detected hallucination patterns (e.g., repetition loops)
  multi_value_info?: MultiValueInfo  // Metadata about multi-event extraction from history notes
}

export interface MultiValueInfo {
  was_split: boolean
  total_events_detected: number
  unique_values_extracted: number
  split_method: string  // 'llm' | 'none'
}

export interface SplitEvent {
  event_text: string
  event_type: string
  event_date: string | null
}

export interface HistoryDetection {
  is_history: boolean
  was_split: boolean
  events_count: number
  detection_methods: string[]
  date_count: number
  event_marker_count: number
  treatment_types_found: string[]
  events: SplitEvent[]
}

export interface ProcessNoteResponse {
  note_id: string
  note_text: string
  annotations: AnnotationResult[]
  processing_time_seconds: number
  timing_breakdown?: Record<string, number>  // Aggregate timing breakdown
  history_detection?: HistoryDetection  // Present when note is a history note
}

export interface BatchProcessRequest {
  note_ids: string[]
  prompt_types: string[]
  fewshot_k?: number
  use_fewshots?: boolean
  fast_mode?: boolean
}

export interface BatchProcessResponse {
  results: ProcessNoteResponse[]
  total_time_seconds: number
  timing_breakdown?: Record<string, number>  // Aggregate timing breakdown
}

// Sequential processing (resilient per-note processing with incremental save)
export interface SequentialProcessRequest {
  note_ids?: string[] | null       // null = process all notes
  prompt_types?: string[] | null   // null = use session defaults
  fewshot_k?: number
  use_fewshots?: boolean
  fast_mode?: boolean
  skip_annotated?: boolean         // Skip notes that already have all annotations
}

export interface SequentialNoteResult {
  note_id: string
  status: 'success' | 'error' | 'skipped'
  error_message?: string | null
  annotations_count: number
  processing_time_seconds: number
}

export interface SequentialProcessResponse {
  session_id: string
  total_notes: number
  processed: number
  skipped: number
  errors: number
  results: SequentialNoteResult[]
  total_time_seconds: number
  timing_summary?: {
    total_processing_time: number
    avg_per_note: number
    min_per_note: number
    max_per_note: number
  }
}

export interface SequentialProgressEvent {
  note_id: string
  status: 'success' | 'error' | 'skipped'
  error_message?: string
  annotations_count?: number
  completed: number
  total: number
  percentage: number
  processing_time_seconds?: number
  history_detection?: HistoryDetection
}

export interface SessionInfo {
  session_id: string
  name: string
  description?: string
  created_at: string
  updated_at: string
  note_count: number
  prompt_types: string[]
  center?: string  // Center/group name (e.g. INT, VGR, MSCI)
  evaluation_mode?: 'validation' | 'evaluation'  // Session mode
}

export interface SessionAnnotation {
  note_id: string
  prompt_type: string
  annotation_text: string
  values: AnnotationValue[]
  edited: boolean
  edited_by?: string
  edited_at?: string
  is_negated?: boolean
  date_info?: AnnotationDateInfo
  evidence_text?: string  // Raw evidence text from structured annotation
  reasoning?: string  // Reasoning from structured annotation
  raw_prompt?: string  // Raw prompt sent to LLM
  raw_response?: string  // Raw response from LLM
  evidence_spans?: EvidenceSpan[]  // Evidence spans for highlighting
  status?: 'success' | 'error' | 'incomplete'  // Annotation status
  evaluation_result?: EvaluationResult  // Evaluation metrics (only in evaluation mode)
  icdo3_code?: ICDO3CodeInfo  // ICD-O-3 code information (for histology/site prompts)
  derived_field_values?: Record<string, string>  // Values resolved via output_word_mappings at annotation time
  hallucination_flags?: HallucinationFlag[]  // Detected hallucination patterns
  multi_value_info?: MultiValueInfo  // Metadata about multi-event extraction from history notes
}

export interface SessionData {
  session_id: string
  name: string
  description?: string
  created_at: string
  updated_at: string
  notes: CSVRow[]
  annotations: Record<string, Record<string, SessionAnnotation>>
  prompt_types: string[]
  center?: string  // Center/group name (e.g. INT, VGR, MSCI)
  evaluation_mode?: 'validation' | 'evaluation'  // Session mode
  report_type_mapping?: Record<string, string[]>  // report_type -> list of prompt_types
  note_prompt_overrides?: Record<string, string[]>  // note_id -> list of additional prompt_types (per-note)
  note_prompt_exclusions?: Record<string, string[]>  // note_id -> list of excluded prompt_types from report_type_mapping
}

// Annotation Preset Types
export interface AnnotationPreset {
  id: string
  name: string
  center: string
  description?: string
  report_type_mapping: Record<string, string[]>
  created_at: string
  updated_at: string
}

export interface AnnotationPresetCreate {
  name: string
  center: string
  description?: string
  report_type_mapping: Record<string, string[]>
}

export interface AnnotationPresetUpdate {
  name?: string
  center?: string
  description?: string
  report_type_mapping?: Record<string, string[]>
}

// API Functions
export const serverApi = {
  getStatus: async (): Promise<ServerStatus> => {
    const response = await api.get('/api/server/status')
    return response.data
  },

  getMetrics: async (): Promise<ServerMetrics> => {
    const response = await api.get('/api/server/metrics')
    return response.data
  },

  listModels: async (): Promise<ModelInfo[]> => {
    const response = await api.get('/api/server/models')
    return response.data
  },

  switchModel: async (model_name: string): Promise<void> => {
    await api.post('/api/server/models/switch', null, {
      params: { model_name },
    })
  },
}

export const promptsApi = {
  listCenters: async (mode: PromptMode = 'standard'): Promise<string[]> => {
    const params: Record<string, string> = {}
    if (mode !== 'standard') params.mode = mode
    const response = await api.get('/api/prompts/centers', { params })
    return response.data
  },

  createCenter: async (center: string, mode: PromptMode = 'standard'): Promise<{ center: string; message: string }> => {
    const params: Record<string, string> = {}
    if (mode !== 'standard') params.mode = mode
    const response = await api.post('/api/prompts/centers', { center: center.trim() }, { params })
    return response.data
  },

  list: async (center?: string, mode: PromptMode = 'standard'): Promise<PromptInfo[]> => {
    const params: Record<string, string> = {}
    if (center) params.center = center
    if (mode !== 'standard') params.mode = mode
    const response = await api.get('/api/prompts', { params })
    return response.data
  },

  get: async (prompt_type: string, center?: string, mode: PromptMode = 'standard'): Promise<PromptInfo> => {
    const params: Record<string, string> = {}
    if (center) params.center = center
    if (mode !== 'standard') params.mode = mode
    const response = await api.get(`/api/prompts/${prompt_type}`, { params })
    return response.data
  },

  create: async (prompt_type: string, template: string, center?: string, mode: PromptMode = 'standard'): Promise<PromptInfo> => {
    const params: Record<string, string> = {}
    if (mode !== 'standard') params.mode = mode
    const response = await api.post('/api/prompts', {
      prompt_type,
      template,
      center: center || 'INT-SARC',
    }, { params })
    return response.data
  },

  update: async (prompt_type: string, template: string, entity_mapping?: EntityMapping, center?: string, mode: PromptMode = 'standard'): Promise<PromptInfo> => {
    const params: Record<string, string> = {}
    if (center) params.center = center
    if (mode !== 'standard') params.mode = mode
    const response = await api.put(`/api/prompts/${prompt_type}`, { template, entity_mapping }, { params })
    return response.data
  },

  rename: async (prompt_type: string, new_name: string, center?: string, mode: PromptMode = 'standard'): Promise<PromptInfo> => {
    const params: Record<string, string> = {}
    if (center) params.center = center
    if (mode !== 'standard') params.mode = mode
    const response = await api.post(`/api/prompts/${prompt_type}/rename`, { new_name }, { params })
    return response.data
  },

  delete: async (prompt_type: string, center?: string, mode: PromptMode = 'standard'): Promise<void> => {
    const params: Record<string, string> = {}
    if (center) params.center = center
    if (mode !== 'standard') params.mode = mode
    await api.delete(`/api/prompts/${prompt_type}`, { params })
  },
}

export const uploadApi = {
  uploadCSV: async (file: File): Promise<CSVUploadResponse> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post('/api/upload/csv', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  uploadFewshots: async (file: File, center: string): Promise<{
    success: boolean
    message: string
    center: string
    prompt_types: string[]
    counts_by_prompt: Record<string, number>
  }> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post(`/api/upload/fewshots?center=${encodeURIComponent(center)}`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  getFewshotsStatus: async (center?: string): Promise<{
    faiss_available: boolean
    simple_fewshots_available: boolean
    prompt_types_with_fewshots: string[]
    counts_by_prompt: Record<string, number>
    total_examples: number
  }> => {
    const params = center ? { center } : {}
    const response = await api.get('/api/upload/fewshots/status', { params })
    return response.data
  },

  deleteFewshots: async (center?: string): Promise<{
    success: boolean
    message: string
    deleted_examples: number
    deleted_prompt_types: number
  }> => {
    const params = center ? { center } : {}
    const response = await api.delete('/api/upload/fewshots', { params })
    return response.data
  },

  downloadFewshots: async (center: string): Promise<Blob> => {
    const response = await api.get('/api/upload/fewshots/download', {
      params: { center },
      responseType: 'blob',
    })
    return response.data
  },

  getReportTypeMappings: async (center?: string): Promise<Record<string, string[]>> => {
    const params = center ? { center } : {}
    const response = await api.get('/api/upload/report-type-mappings', { params })
    return response.data
  },

  saveReportTypeMappings: async (mapping: Record<string, string[]>, center?: string): Promise<{
    success: boolean
    message: string
  }> => {
    const params = center ? { center } : {}
    const response = await api.post('/api/upload/report-type-mappings', mapping, { params })
    return response.data
  },
}

export const annotateApi = {
  processNote: async (
    session_id: string,
    note_id: string,
    note_text: string,
    prompt_types: string[],
    fewshot_k: number = 5,
    use_fewshots: boolean = true,
    signal?: AbortSignal
  ): Promise<ProcessNoteResponse> => {
    const response = await api.post(
      `/api/annotate/process?session_id=${session_id}&note_text=${encodeURIComponent(note_text)}`,
      {
        note_id,
        prompt_types,
        fewshot_k,
        use_fewshots,
      },
      { signal }
    )
    return response.data
  },

  batchProcess: async (
    session_id: string,
    request: BatchProcessRequest,
    signal?: AbortSignal
  ): Promise<BatchProcessResponse> => {
    const response = await api.post(
      `/api/annotate/batch`,
      request,
      {
        params: { session_id },
        timeout: 300_000, // 5 minutes for batch operations
        signal,
      }
    )
    return response.data
  },

  /**
   * SSE-streaming batch process. Sends progress events as each prompt
   * completes, preventing reverse-proxy idle timeouts.
   * Falls back to standard batchProcess on failure.
   */
  batchProcessStream: async (
    session_id: string,
    request: BatchProcessRequest,
    onProgress?: (data: {
      completed: number
      total: number
      note_id: string
      prompt_type: string
      percentage: number
      history_detection?: HistoryDetection
    }) => void,
    signal?: AbortSignal
  ): Promise<BatchProcessResponse> => {
    const url = `${API_BASE_URL}/api/annotate/batch/stream?session_id=${encodeURIComponent(session_id)}`

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal,
    })

    if (!response.ok) {
      // Try to parse error detail, then throw
      let detail = `Batch streaming failed (${response.status})`
      try {
        const err = await response.json()
        if (err.detail) detail = err.detail
      } catch { /* ignore parse errors */ }
      throw new Error(detail)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalResult: BatchProcessResponse | null = null

    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        buffer += decoder.decode()
      } else {
        buffer += decoder.decode(value, { stream: true })
      }

      // Normalize \r\n to \n (sse-starlette uses \r\n)
      buffer = buffer.replace(/\r\n/g, '\n')

      // Parse SSE events from buffer
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || '' // last part may be incomplete

      // When stream ends, treat leftover buffer as a final event too
      if (done && buffer.trim()) {
        parts.push(buffer)
        buffer = ''
      }

      for (const part of parts) {
        let eventType = ''
        let eventData = ''
        for (const line of part.split('\n')) {
          const trimmed = line.trim()
          if (trimmed.startsWith('event:')) {
            eventType = trimmed.slice(6).trim()
          } else if (trimmed.startsWith('data:')) {
            eventData += trimmed.slice(5).trim()
          }
        }
        if (!eventData) continue

        if (eventType === 'progress' && onProgress) {
          try { onProgress(JSON.parse(eventData)) } catch { /* skip bad events */ }
        } else if (eventType === 'complete') {
          try { finalResult = JSON.parse(eventData) } catch { /* skip bad events */ }
        }
      }

      if (done) break
    }

    if (!finalResult) throw new Error('Stream ended without a complete event')
    return finalResult
  },

  selectICDO3Candidate: async (
    sessionId: string,
    noteId: string,
    promptType: string,
    candidateIndex: number
  ): Promise<{ success: boolean; icdo3_code: ICDO3CodeInfo; message: string }> => {
    const response = await api.post('/api/annotate/icdo3/select', null, {
      params: {
        session_id: sessionId,
        note_id: noteId,
        prompt_type: promptType,
        candidate_index: candidateIndex,
      },
    })
    return response.data
  },

  // Unified ICD-O-3 Code APIs
  searchICDO3Codes: async (
    query: string,
    morphology?: string,
    topography?: string,
    limit: number = 20
  ): Promise<ICDO3SearchResponse> => {
    const params: Record<string, string | number> = { q: query, limit }
    if (morphology) params.morphology = morphology
    if (topography) params.topography = topography
    const response = await api.get('/api/annotate/icdo3/search', { params })
    return response.data
  },

  validateICDO3Combination: async (
    morphology: string,
    topography: string
  ): Promise<ICDO3ValidationResult> => {
    const response = await api.get('/api/annotate/icdo3/validate', {
      params: { morphology, topography },
    })
    return response.data
  },

  saveUnifiedICDO3Code: async (
    sessionId: string,
    noteId: string,
    queryCode: string
  ): Promise<ICDO3CombineResponse> => {
    const response = await api.post(
      '/api/annotate/icdo3/combine',
      { query_code: queryCode },
      { params: { session_id: sessionId, note_id: noteId } }
    )
    return response.data
  },

  getValidTopographies: async (
    morphology: string,
    limit: number = 50
  ): Promise<ICDO3TopographiesResponse> => {
    const response = await api.get('/api/annotate/icdo3/topographies', {
      params: { morphology, limit },
    })
    return response.data
  },

  getValidMorphologies: async (
    topography: string,
    limit: number = 50
  ): Promise<ICDO3MorphologiesResponse> => {
    const response = await api.get('/api/annotate/icdo3/morphologies', {
      params: { topography, limit },
    })
    return response.data
  },

  getUnifiedICDO3Code: async (
    sessionId: string,
    noteId: string
  ): Promise<ICDO3UnifiedCodeResponse> => {
    const response = await api.get(`/api/annotate/icdo3/unified/${noteId}`, {
      params: { session_id: sessionId },
    })
    return response.data
  },

  // Sequential processing (resilient per-note with incremental save)
  sequentialProcess: async (
    session_id: string,
    request: SequentialProcessRequest,
    signal?: AbortSignal
  ): Promise<SequentialProcessResponse> => {
    const response = await api.post(
      `/api/annotate/sequential`,
      request,
      {
        params: { session_id },
        timeout: 0, // no timeout for long-running sequential processing
        signal,
      }
    )
    return response.data
  },

  /**
   * SSE-streaming sequential process. Emits progress events after each note.
   * Server saves annotations to disk after each note (crash resilient).
   * Falls back to non-streaming sequentialProcess on failure.
   */
  sequentialProcessStream: async (
    session_id: string,
    request: SequentialProcessRequest,
    onProgress?: (data: SequentialProgressEvent) => void,
    signal?: AbortSignal
  ): Promise<SequentialProcessResponse> => {
    const url = `${API_BASE_URL}/api/annotate/sequential/stream?session_id=${encodeURIComponent(session_id)}`

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal,
    })

    if (!response.ok) {
      let detail = `Sequential streaming failed (${response.status})`
      try {
        const err = await response.json()
        if (err.detail) detail = err.detail
      } catch { /* ignore parse errors */ }
      throw new Error(detail)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalResult: SequentialProcessResponse | null = null

    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        buffer += decoder.decode()
      } else {
        buffer += decoder.decode(value, { stream: true })
      }

      // Normalize \r\n to \n (sse-starlette uses \r\n)
      buffer = buffer.replace(/\r\n/g, '\n')

      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''

      // When stream ends, treat leftover buffer as a final event too
      if (done && buffer.trim()) {
        parts.push(buffer)
        buffer = ''
      }

      for (const part of parts) {
        let eventType = ''
        let eventData = ''
        for (const line of part.split('\n')) {
          const trimmed = line.trim()
          if (trimmed.startsWith('event:')) {
            eventType = trimmed.slice(6).trim()
          } else if (trimmed.startsWith('data:')) {
            eventData += trimmed.slice(5).trim()
          }
        }
        if (!eventData) continue

        if (eventType === 'progress' && onProgress) {
          try { onProgress(JSON.parse(eventData)) } catch { /* skip bad events */ }
        } else if (eventType === 'complete') {
          try { finalResult = JSON.parse(eventData) } catch { /* skip bad events */ }
        } else if (eventType === 'error') {
          try {
            const errData = JSON.parse(eventData)
            throw new Error(errData.detail || 'Sequential processing error')
          } catch (e) {
            if (e instanceof Error && e.message !== 'Sequential processing error') throw e
            throw new Error('Sequential processing error')
          }
        }
      }

      if (done) break
    }

    if (!finalResult) throw new Error('Stream ended without a complete event')
    return finalResult
  },
}

export const sessionsApi = {
  create: async (
    name: string,
    csv_data: CSVRow[],
    prompt_types: string[],
    evaluation_mode?: 'validation' | 'evaluation',
    description?: string,
    report_type_mapping?: Record<string, string[]>
  ): Promise<SessionInfo> => {
    const response = await api.post('/api/sessions', {
      name,
      description,
      csv_data,
      evaluation_mode,
      prompt_types,
      report_type_mapping,
    })
    return response.data
  },

  get: async (session_id: string): Promise<SessionData> => {
    const response = await api.get(`/api/sessions/${session_id}`)
    return response.data
  },

  update: async (
    session_id: string,
    annotations: Record<string, Record<string, SessionAnnotation>>
  ): Promise<SessionData> => {
    const response = await api.put(`/api/sessions/${session_id}`, {
      annotations,
    })
    return response.data
  },

  delete: async (session_id: string): Promise<{ success: boolean; message: string }> => {
    const response = await api.delete(`/api/sessions/${session_id}`)
    return response.data
  },

  list: async (): Promise<SessionInfo[]> => {
    const response = await api.get('/api/sessions')
    return response.data
  },

  addPromptTypes: async (
    session_id: string,
    prompt_types: string[]
  ): Promise<SessionData> => {
    const response = await api.post(`/api/sessions/${session_id}/prompt_types`, {
      prompt_types,
    })
    return response.data
  },

  removePromptTypes: async (
    session_id: string,
    prompt_types: string[]
  ): Promise<SessionData> => {
    // Use query parameters for DELETE request
    const params = new URLSearchParams()
    prompt_types.forEach((pt) => params.append('prompt_types', pt))
    const response = await api.delete(`/api/sessions/${session_id}/prompt_types?${params.toString()}`)
    return response.data
  },

  updateMetadata: async (
    session_id: string,
    update: { name?: string; report_type_mapping?: Record<string, string[]>; note_prompt_overrides?: Record<string, string[]>; note_prompt_exclusions?: Record<string, string[]> }
  ): Promise<SessionData> => {
    const response = await api.patch(`/api/sessions/${session_id}`, update)
    return response.data
  },

  validateExport: async (session_id: string): Promise<ExportValidationResponse> => {
    const response = await api.get(`/api/sessions/${session_id}/export/validate`)
    return response.data
  },

  resolveConflicts: async (
    session_id: string,
    entries: ConflictResolveEntry[],
  ): Promise<ConflictResolveResponse> => {
    const response = await api.post(
      `/api/sessions/${session_id}/conflicts/resolve`,
      { entries },
    )
    return response.data
  },

  exportLabels: async (session_id: string): Promise<{ blob: Blob; excludedRows: ExcludedRow[] }> => {
    const response = await api.get(`/api/sessions/${session_id}/export`, {
      responseType: 'blob',
    })
    const excludedRows = parseExcludedRowsHeader(response.headers['x-excluded-rows'])
    return { blob: response.data, excludedRows }
  },

  exportCodes: async (session_id: string): Promise<{ blob: Blob; excludedRows: ExcludedRow[] }> => {
    const response = await api.get(`/api/sessions/${session_id}/export/codes`, {
      responseType: 'blob',
    })
    const excludedRows = parseExcludedRowsHeader(response.headers['x-excluded-rows'])
    return { blob: response.data, excludedRows }
  },

  exportSession: async (session_id: string): Promise<Blob> => {
    const response = await api.get(`/api/sessions/${session_id}/export/session`, {
      responseType: 'blob',
    })
    return response.data
  },

  importSession: async (file: File): Promise<SessionInfo> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post('/api/sessions/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  },

  getDiagnoses: async (session_id: string): Promise<DiagnosisValidationReport> => {
    const response = await api.get(`/api/sessions/${session_id}/diagnoses`)
    return response.data
  },

  resolvePatientDiagnosis: async (
    session_id: string,
    patient_id: string,
    query_code: string,
  ): Promise<PatientDiagnosisResolveResponse> => {
    const response = await api.post(
      `/api/sessions/${session_id}/diagnoses/${encodeURIComponent(patient_id)}/resolve`,
      { query_code },
    )
    return response.data
  },

  resolveAllDiagnoses: async (session_id: string): Promise<DiagnosisValidationReport> => {
    const response = await api.post(`/api/sessions/${session_id}/diagnoses/resolve-all`)
    return response.data
  },
}

export const presetsApi = {
  list: async (center?: string): Promise<AnnotationPreset[]> => {
    const params = center ? { center } : {}
    const response = await api.get('/api/presets', { params })
    return response.data
  },

  get: async (id: string): Promise<AnnotationPreset> => {
    const response = await api.get(`/api/presets/${id}`)
    return response.data
  },

  create: async (data: AnnotationPresetCreate): Promise<AnnotationPreset> => {
    const response = await api.post('/api/presets', data)
    return response.data
  },

  update: async (id: string, data: AnnotationPresetUpdate): Promise<AnnotationPreset> => {
    const response = await api.put(`/api/presets/${id}`, data)
    return response.data
  },

  delete: async (id: string): Promise<{ success: boolean; message: string }> => {
    const response = await api.delete(`/api/presets/${id}`)
    return response.data
  },
}

export default api

