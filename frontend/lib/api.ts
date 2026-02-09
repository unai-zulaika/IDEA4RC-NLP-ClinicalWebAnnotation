/**
 * API Client for Clinical Data Curation Platform
 */

import axios from 'axios'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001'

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

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

export interface EntityFieldMapping {
  template_placeholder: string
  entity_type: string
  field_name: string
  hardcoded_value?: string
  value_code_mappings?: Record<string, string>
}

export interface EntityMapping {
  entity_type: string
  fact_trigger?: string
  field_mappings: EntityFieldMapping[]
}

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
}

export interface ProcessNoteResponse {
  note_id: string
  note_text: string
  annotations: AnnotationResult[]
  processing_time_seconds: number
}

export interface BatchProcessRequest {
  note_ids: string[]
  prompt_types: string[]
  fewshot_k?: number
  use_fewshots?: boolean
}

export interface BatchProcessResponse {
  results: ProcessNoteResponse[]
  total_time_seconds: number
}

export interface SessionInfo {
  session_id: string
  name: string
  description?: string
  created_at: string
  updated_at: string
  note_count: number
  prompt_types: string[]
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
  evaluation_mode?: 'validation' | 'evaluation'  // Session mode
  report_type_mapping?: Record<string, string[]>  // report_type -> list of prompt_types
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
  listCenters: async (): Promise<string[]> => {
    const response = await api.get('/api/prompts/centers')
    return response.data
  },

  createCenter: async (center: string): Promise<{ center: string; message: string }> => {
    const response = await api.post('/api/prompts/centers', { center: center.trim() })
    return response.data
  },

  list: async (center?: string): Promise<PromptInfo[]> => {
    const params = center ? { center } : {}
    const response = await api.get('/api/prompts', { params })
    return response.data
  },

  get: async (prompt_type: string, center?: string): Promise<PromptInfo> => {
    const params = center ? { center } : {}
    const response = await api.get(`/api/prompts/${prompt_type}`, { params })
    return response.data
  },

  create: async (prompt_type: string, template: string, center?: string): Promise<PromptInfo> => {
    const response = await api.post('/api/prompts', {
      prompt_type,
      template,
      center: center || 'INT',
    })
    return response.data
  },

  update: async (prompt_type: string, template: string, entity_mapping?: EntityMapping, center?: string): Promise<PromptInfo> => {
    const params = center ? { center } : {}
    const response = await api.put(`/api/prompts/${prompt_type}`, { template, entity_mapping }, { params })
    return response.data
  },

  rename: async (prompt_type: string, new_name: string, center?: string): Promise<PromptInfo> => {
    const params = center ? { center } : {}
    const response = await api.post(`/api/prompts/${prompt_type}/rename`, { new_name }, { params })
    return response.data
  },

  delete: async (prompt_type: string, center?: string): Promise<void> => {
    const params = center ? { center } : {}
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

  uploadFewshots: async (file: File): Promise<{
    success: boolean
    message: string
    prompt_types: string[]
    counts_by_prompt: Record<string, number>
  }> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post('/api/upload/fewshots', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  getFewshotsStatus: async (): Promise<{
    faiss_available: boolean
    simple_fewshots_available: boolean
    prompt_types_with_fewshots: string[]
    counts_by_prompt: Record<string, number>
    total_examples: number
  }> => {
    const response = await api.get('/api/upload/fewshots/status')
    return response.data
  },

  deleteFewshots: async (): Promise<{
    success: boolean
    message: string
    deleted_examples: number
    deleted_prompt_types: number
  }> => {
    const response = await api.delete('/api/upload/fewshots')
    return response.data
  },

  getReportTypeMappings: async (): Promise<Record<string, string[]>> => {
    const response = await api.get('/api/upload/report-type-mappings')
    return response.data
  },

  saveReportTypeMappings: async (mapping: Record<string, string[]>): Promise<{
    success: boolean
    message: string
  }> => {
    const response = await api.post('/api/upload/report-type-mappings', mapping)
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
    use_fewshots: boolean = true
  ): Promise<ProcessNoteResponse> => {
    const response = await api.post(
      `/api/annotate/process?session_id=${session_id}&note_text=${encodeURIComponent(note_text)}`,
      {
        note_id,
        prompt_types,
        fewshot_k,
        use_fewshots,
      }
    )
    return response.data
  },

  batchProcess: async (
    session_id: string,
    request: BatchProcessRequest
  ): Promise<BatchProcessResponse> => {
    const response = await api.post(
      `/api/annotate/batch`,
      request,
      {
        params: { session_id },
      }
    )
    return response.data
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
    update: { name?: string; report_type_mapping?: Record<string, string[]> }
  ): Promise<SessionData> => {
    const response = await api.patch(`/api/sessions/${session_id}`, update)
    return response.data
  },

  exportLabels: async (session_id: string): Promise<Blob> => {
    const response = await api.get(`/api/sessions/${session_id}/export`, {
      responseType: 'blob',
    })
    return response.data
  },

  exportCodes: async (session_id: string): Promise<Blob> => {
    const response = await api.get(`/api/sessions/${session_id}/export/codes`, {
      responseType: 'blob',
    })
    return response.data
  },
}

export default api

