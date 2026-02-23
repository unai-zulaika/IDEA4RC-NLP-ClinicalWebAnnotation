"""
Pydantic schemas for request/response models
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime


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
class EntityFieldMapping(BaseModel):
    """Mapping from template placeholder to entity field"""
    template_placeholder: str = Field(..., description="The placeholder in the template, e.g., '[select intention]'")
    entity_type: str = Field(..., description="The entity type, e.g., 'Radiotherapy'")
    field_name: str = Field(..., description="The field name on the entity, e.g., 'intent'")
    hardcoded_value: Optional[str] = Field(None, description="If set, use this value for the field instead of extracting from the annotation")
    value_code_mappings: Optional[Dict[str, str]] = Field(None, description="Map specific extracted values to code IDs, e.g. {'1': '1634371', '2': '1634372'}")


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


class ProcessNoteRequest(BaseModel):
    note_id: str
    prompt_types: List[str]
    fewshot_k: int = 5
    use_fewshots: bool = True


class ProcessNoteResponse(BaseModel):
    note_id: str
    note_text: str
    annotations: List[AnnotationResult]
    processing_time_seconds: float


class BatchProcessRequest(BaseModel):
    note_ids: List[str]
    prompt_types: List[str]
    fewshot_k: int = 5
    use_fewshots: bool = True


class BatchProcessResponse(BaseModel):
    results: List[ProcessNoteResponse]
    total_time_seconds: float


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


class SessionMetadataUpdate(BaseModel):
    name: Optional[str] = None
    report_type_mapping: Optional[Dict[str, List[str]]] = None


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

