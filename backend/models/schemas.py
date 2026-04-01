"""
Pydantic schemas for request/response models
"""

from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime

from models.annotation_models import HallucinationFlag


# Server Status Schemas
class ServerStatus(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    
    status: str
    model_name: Optional[str] = None
    endpoint: Optional[str] = None


class ServerMetrics(BaseModel):
    gpu_memory_used_gb: Optional[float] = None
    gpu_memory_total_gb: Optional[float] = None
    gpu_utilization_percent: Optional[float] = None
    throughput_tokens_per_sec: Optional[float] = None
    throughput_requests_per_sec: Optional[float] = None
    active_requests: Optional[int] = None


class ModelInfo(BaseModel):
    id: str
    name: str
    is_active: bool = False


# Prompt Schemas
class OutputWordMapping(BaseModel):
    """Regex pattern → value mapping applied against LLM final_output at annotation time"""
    pattern: str = Field(..., description="Regex pattern tested against the LLM final_output string")
    value: str = Field(..., description="Value to store for this field if the pattern matches")
    flags: Optional[str] = Field(None, description="Comma-separated regex flags: 'IGNORECASE', 'MULTILINE'")


class EntityFieldMapping(BaseModel):
    """Mapping from template placeholder to entity field"""
    template_placeholder: str = Field(..., description="The placeholder in the template, e.g., '[select intention]'")
    entity_type: str = Field(..., description="The entity type, e.g., 'Radiotherapy'")
    field_name: str = Field(..., description="The field name on the entity, e.g., 'intent'")
    hardcoded_value: Optional[str] = Field(None, description="If set, use this value for the field instead of extracting from the annotation")
    value_code_mappings: Optional[Dict[str, str]] = Field(None, description="Map specific extracted values to code IDs, e.g. {'1': '1634371', '2': '1634372'}")
    output_word_mappings: Optional[List["OutputWordMapping"]] = Field(None, description="Ordered list of regex patterns tested against LLM final_output; first match sets field value")

    @field_validator('value_code_mappings', mode='before')
    @classmethod
    def coerce_list_values_to_str(cls, val):
        if val is None:
            return val
        return {k: (str(v[0]) if isinstance(v, list) else str(v) if not isinstance(v, str) else v) for k, v in val.items()}


class EntityMapping(BaseModel):
    """Mapping configuration for a prompt"""
    entity_type: str = Field(..., description="The main entity type created by this prompt, e.g., 'Radiotherapy'")
    fact_trigger: Optional[str] = Field(None, description="Text pattern that triggers entity creation, e.g., 'pre-operative radiotherapy'")
    field_mappings: List[EntityFieldMapping] = Field(default_factory=list, description="Mappings from template placeholders to entity fields")


class PromptInfo(BaseModel):
    prompt_type: str
    template: str
    report_types: Optional[List[str]] = None
    entity_mapping: Optional[EntityMapping] = None
    center: Optional[str] = None  # Center/group (e.g. INT, MSCI, VGR)


class CenterCreate(BaseModel):
    center: str


class PromptUpdate(BaseModel):
    template: str
    entity_mapping: Optional[EntityMapping] = None


class PromptRename(BaseModel):
    new_name: str


# CSV Upload Schemas
class CSVUploadResponse(BaseModel):
    success: bool
    message: str
    row_count: int
    columns: List[str]
    preview: List[Dict[str, Any]]  # First 10 rows for display
    all_rows: List[Dict[str, Any]]  # All rows for session creation
    session_id: Optional[str] = None  # Deprecated - no longer created here
    has_annotations: Optional[bool] = False  # True if annotations column exists and has values
    report_types: Optional[List[str]] = None  # Unique report types found in CSV
    duplicate_note_ids_detected: Optional[bool] = False  # True if duplicate note_ids were found and deduplicated
    duplicate_text_detected: bool = False  # True if rows with duplicate text content were removed
    duplicate_text_removed_count: int = 0  # Number of rows removed due to duplicate text
    duplicate_text_note_ids: List[str] = []  # note_ids of the removed rows


class CSVRow(BaseModel):
    text: str
    date: str
    p_id: str
    note_id: str
    report_type: str
    annotations: Optional[str] = None  # Optional annotations column


# Annotation Schemas
class EvidenceSpan(BaseModel):
    start: int
    end: int
    text: str
    prompt_type: str


class AnnotationValue(BaseModel):
    value: str
    evidence_spans: List[EvidenceSpan] = []
    reasoning: Optional[str] = None


class ICDO3CodeCandidate(BaseModel):
    """A single ICD-O-3 code candidate from CSV"""
    rank: int  # Position in candidate list (1-5)
    query_code: str  # Full query code from CSV (e.g., "8940/0-C00.2")
    morphology_code: Optional[str] = None  # Morphology code (e.g., "8940/0")
    topography_code: Optional[str] = None  # Topography code (e.g., "C00.2")
    name: str  # NAME column from CSV - the label shown to user
    match_score: float  # Similarity/relevance score (0.0-1.0)
    match_method: str  # How this candidate was found


class ICDO3CodeInfo(BaseModel):
    """ICD-O-3 code information with multi-candidate support"""
    code: str  # Currently selected ICD-O-3 code (e.g., "8805/3" or "8805/3-C71.7")
    topography_code: Optional[str] = None  # Topography code (e.g., "C71.7")
    morphology_code: Optional[str] = None  # Morphology code (e.g., "8805/3")
    histology_code: Optional[str] = None  # Histology code (e.g., "8805")
    behavior_code: Optional[str] = None  # Behavior code (e.g., "3")
    description: Optional[str] = None  # Description of the code
    confidence: Optional[float] = None  # Confidence score if available
    query_code: Optional[str] = None  # Query code from CSV (e.g., "8940/0-C00.2")
    match_method: Optional[str] = None  # How the code was matched ("exact", "llm_csv", "pattern", etc.)
    match_score: Optional[float] = None  # Match confidence score (0.0-1.0)
    # Multi-candidate support
    candidates: List[ICDO3CodeCandidate] = []  # Top 5 candidates from CSV
    selected_candidate_index: int = 0  # Which candidate is currently selected (0-4)
    user_selected: bool = False  # True if user manually selected a candidate


class ChunkInfo(BaseModel):
    """Metadata recorded when a note is too long and processed in chunks."""
    was_chunked: bool = False
    total_chunks: Optional[int] = None
    answer_chunk_index: Optional[int] = None  # 1-indexed chunk that produced the answer
    chunks_exhausted: bool = False  # True if all chunks tried without a confident answer


class AnnotationResult(BaseModel):
    prompt_type: str
    annotation_text: str
    values: List[AnnotationValue] = []
    confidence_score: Optional[float] = None
    evidence_spans: List[EvidenceSpan] = []
    reasoning: Optional[str] = None
    is_negated: Optional[bool] = None
    date_info: Optional[Dict[str, Any]] = None  # Date information from structured annotation
    evidence_text: Optional[str] = None  # Raw evidence text from structured annotation
    raw_prompt: Optional[str] = None  # Raw prompt sent to LLM
    raw_response: Optional[str] = None  # Raw response from LLM
    status: Optional[str] = "success"  # "success", "error", "incomplete" - indicates annotation status
    evaluation_result: Optional[Dict[str, Any]] = None  # Evaluation metrics (only in evaluation mode)
    icdo3_code: Optional[ICDO3CodeInfo] = None  # ICD-O-3 code information (for histology/site prompts)
    timing_breakdown: Optional[Dict[str, float]] = None  # Per-step timing breakdown
    chunk_info: Optional[ChunkInfo] = None  # Set when note was split into chunks due to context limit
    derived_field_values: Optional[Dict[str, str]] = None  # Values resolved via output_word_mappings at annotation time
    hallucination_flags: Optional[List[HallucinationFlag]] = None  # Detected hallucination patterns (e.g., repetition loops)
    multi_value_info: Optional[Dict[str, Any]] = None  # Metadata about multi-event extraction from history notes


class ProcessNoteRequest(BaseModel):
    note_id: str
    prompt_types: List[str]
    fewshot_k: int = 5
    use_fewshots: bool = True
    fast_mode: bool = False


class ProcessNoteResponse(BaseModel):
    note_id: str
    note_text: str
    annotations: List[AnnotationResult]
    processing_time_seconds: float
    timing_breakdown: Optional[Dict[str, float]] = None  # Aggregate timing breakdown
    history_detection: Optional[Dict[str, Any]] = None  # Present when note is a history note


class BatchProcessRequest(BaseModel):
    note_ids: List[str]
    prompt_types: List[str]
    fewshot_k: int = 5
    use_fewshots: bool = True
    fast_mode: bool = False


class BatchProcessResponse(BaseModel):
    results: List[ProcessNoteResponse]
    total_time_seconds: float
    timing_breakdown: Optional[Dict[str, float]] = None  # Aggregate timing breakdown


# Sequential Processing Schemas
class SequentialProcessRequest(BaseModel):
    note_ids: Optional[List[str]] = None        # None = process all notes in session
    prompt_types: Optional[List[str]] = None     # None = use session's prompt_types
    fewshot_k: int = 5
    use_fewshots: bool = True
    fast_mode: bool = False
    skip_annotated: bool = False                 # Skip notes that already have all prompt annotations


class SequentialNoteResult(BaseModel):
    note_id: str
    status: str                                  # "success" | "error" | "skipped"
    error_message: Optional[str] = None
    annotations_count: int = 0
    processing_time_seconds: float = 0.0


class SequentialProcessResponse(BaseModel):
    session_id: str
    total_notes: int
    processed: int
    skipped: int
    errors: int
    results: List[SequentialNoteResult]
    total_time_seconds: float
    timing_summary: Optional[Dict[str, Any]] = None


# Session Schemas
class SessionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    csv_data: List[CSVRow]
    prompt_types: List[str]
    center: Optional[str] = None  # Center/group name (e.g. INT, VGR, MSCI); inferred from prompt_types if omitted
    evaluation_mode: Optional[str] = "validation"  # "validation" or "evaluation"
    report_type_mapping: Optional[Dict[str, List[str]]] = None  # report_type -> list of prompt_types


class SessionInfo(BaseModel):
    session_id: str
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    note_count: int
    prompt_types: List[str]
    center: Optional[str] = None


class SessionAnnotation(BaseModel):
    note_id: str
    prompt_type: str
    annotation_text: str
    values: List[AnnotationValue] = []
    edited: bool = False
    edited_by: Optional[str] = None
    edited_at: Optional[datetime] = None
    is_negated: Optional[bool] = None
    date_info: Optional[Dict[str, Any]] = None  # Date information from structured annotation
    evidence_text: Optional[str] = None  # Raw evidence text from structured annotation
    reasoning: Optional[str] = None  # Reasoning from structured annotation
    raw_prompt: Optional[str] = None  # Raw prompt sent to LLM
    raw_response: Optional[str] = None  # Raw response from LLM
    evidence_spans: List[EvidenceSpan] = []  # Evidence spans for highlighting
    status: Optional[str] = "success"  # "success", "error", "incomplete" - indicates annotation status
    # Evaluation results (only in evaluation mode)
    evaluation_result: Optional[Dict[str, Any]] = None  # Evaluation metrics: exact_match, similarity_score, overall_match, etc.
    # ICD-O-3 code information (for histology/site prompts)
    icdo3_code: Optional[Dict[str, Any]] = None  # ICD-O-3 code information with query_code, match_method, match_score
    chunk_info: Optional[ChunkInfo] = None  # Set when note was split into chunks due to context limit
    derived_field_values: Optional[Dict[str, str]] = None  # Values resolved via output_word_mappings
    hallucination_flags: Optional[List[Dict[str, Any]]] = None  # Detected hallucination patterns (e.g., repetition loops)
    multi_value_info: Optional[Dict[str, Any]] = None  # Metadata about multi-event extraction from history notes


class SessionData(BaseModel):
    session_id: str
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    notes: List[CSVRow]
    annotations: Dict[str, Dict[str, SessionAnnotation]]  # note_id -> prompt_type -> annotation
    prompt_types: List[str]
    center: Optional[str] = None  # Center/group name inferred from prompt_types
    evaluation_mode: Optional[str] = "validation"  # "validation" or "evaluation"
    report_type_mapping: Optional[Dict[str, List[str]]] = None  # report_type -> list of prompt_types
    note_prompt_overrides: Optional[Dict[str, List[str]]] = None  # note_id -> list of additional prompt_types (per-note)
    note_prompt_exclusions: Optional[Dict[str, List[str]]] = None  # note_id -> list of excluded prompt_types from report_type_mapping


class SessionMetadataUpdate(BaseModel):
    name: Optional[str] = None
    report_type_mapping: Optional[Dict[str, List[str]]] = None
    note_prompt_overrides: Optional[Dict[str, List[str]]] = None
    note_prompt_exclusions: Optional[Dict[str, List[str]]] = None


class SessionUpdate(BaseModel):
    annotations: Dict[str, Dict[str, SessionAnnotation]]  # note_id -> prompt_type -> annotation


class SessionPromptTypesUpdate(BaseModel):
    prompt_types: List[str]


# ICD-O-3 Unified Code Schemas
class ICDO3SearchResult(BaseModel):
    """Search result for ICD-O-3 codes"""
    query_code: str  # Full query code (e.g., "8031/3-C00.2")
    morphology_code: str  # Morphology code (e.g., "8031/3")
    topography_code: str  # Topography code (e.g., "C00.2")
    name: str  # Description from CSV NAME column
    match_score: float  # Relevance score (0.0-1.0)


class ICDO3SearchResponse(BaseModel):
    """Response for ICD-O-3 search endpoint"""
    results: List[ICDO3SearchResult]
    total_count: int
    query: str
    morphology_filter: Optional[str] = None
    topography_filter: Optional[str] = None


class ICDO3ValidationResult(BaseModel):
    """Validation result for morphology+topography combination"""
    valid: bool  # Whether the combination exists in CSV
    query_code: Optional[str] = None  # Full query code if valid
    name: Optional[str] = None  # Description if valid
    morphology_valid: bool  # Whether morphology code exists
    topography_valid: bool  # Whether topography code exists


class UnifiedICDO3Code(BaseModel):
    """Unified ICD-O-3 diagnosis code combining histology and topography"""
    query_code: str  # Full code (e.g., "8031/3-C00.2")
    morphology_code: str  # Morphology/histology code (e.g., "8031/3")
    topography_code: str  # Topography/site code (e.g., "C00.2")
    name: str  # Description from CSV
    source: str  # "combined", "user_override", "search_selected"
    user_selected: bool = False  # True if user manually selected
    validation: Dict[str, bool] = {}  # Validation status fields
    created_at: Optional[datetime] = None


class ICDO3CombineRequest(BaseModel):
    """Request to save unified ICD-O-3 code"""
    query_code: str  # The selected unified code


class ICDO3CombineResponse(BaseModel):
    """Response from saving unified ICD-O-3 code"""
    success: bool
    unified_code: Optional[UnifiedICDO3Code] = None
    message: Optional[str] = None


# Patient Diagnosis Schemas (patient-level ICD-O-3 resolution)
class PatientDiagnosisCode(BaseModel):
    """A single ICD-O-3 code found in a patient's annotations"""
    code: str                # morphology_code or topography_code
    note_id: str
    description: Optional[str] = None
    prompt_type: Optional[str] = None


class PatientDiagnosisInfo(BaseModel):
    """Diagnosis status for a single patient"""
    patient_id: str
    status: str              # "auto_resolved", "needs_review", "manually_resolved", "skipped"
    review_reasons: List[str] = []
    histology_codes: List[PatientDiagnosisCode] = []
    topography_codes: List[PatientDiagnosisCode] = []
    resolved_code: Optional[UnifiedICDO3Code] = None
    csv_id: Optional[str] = None         # numeric ID column from CSV
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None    # "auto" | "user"


class PatientDiagnosisResolveRequest(BaseModel):
    """Request to manually resolve a patient's diagnosis"""
    query_code: str


class PatientDiagnosisResolveResponse(BaseModel):
    """Response from resolving a patient's diagnosis"""
    success: bool
    diagnosis: Optional[PatientDiagnosisInfo] = None
    message: Optional[str] = None


class DiagnosisValidationReport(BaseModel):
    """Summary of diagnosis resolution status across all patients"""
    patients: List[PatientDiagnosisInfo]
    total_patients: int
    auto_resolved: int
    needs_review: int
    manually_resolved: int
    skipped: int


# Annotation Preset Schemas
class AnnotationPresetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    center: str = Field(..., min_length=1)
    description: Optional[str] = None
    report_type_mapping: Dict[str, List[str]]


class AnnotationPresetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    center: Optional[str] = None
    description: Optional[str] = None
    report_type_mapping: Optional[Dict[str, List[str]]] = None


class AnnotationPreset(BaseModel):
    id: str
    name: str
    center: str
    description: Optional[str] = None
    report_type_mapping: Dict[str, List[str]]
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Export validation (cardinality-based conflict detection)
# ---------------------------------------------------------------------------

class ExportConflict(BaseModel):
    patient_id: str
    core_variable: str
    date_ref: Optional[str] = None  # None for non-repeatable entities
    conflicting_values: List[str]
    conflict_type: str  # "non_repeatable" | "repeatable_same_date"


class ExportValidationResponse(BaseModel):
    valid: bool
    conflicts: List[ExportConflict] = []
    row_count: int = 0
    deduplicated_count: int = 0

