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
    # Few-shot retrieval health. "faiss" means semantic retrieval is live;
    # "static" means FAISS is unavailable and prompts fall back to first-k
    # examples, which changes results — fewshot_error carries the reason.
    fewshot_retrieval: Optional[str] = None
    fewshot_error: Optional[str] = None
    fewshot_indexes: Optional[int] = None
    # Model ids the vLLM server actually serves, and why a call would fail.
    # status becomes "model_mismatch" when model_name is not among them.
    served_models: Optional[List[str]] = None
    error: Optional[str] = None


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
    # Descriptive metadata only — the export path reads entity_type/field_name/
    # value_code_mappings straight from prompts.json and never consults this.
    # It was required, so a hand-edited prompt that omitted it (multifocality, in
    # all four centres) made GET /api/prompts raise and every prompt vanish from
    # the UI. Defaulted rather than required: an incomplete mapping should
    # degrade one prompt's metadata, not hide the whole catalogue.
    template_placeholder: str = Field("", description="The placeholder in the template, e.g., '[select intention]'")
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
    # True when the auto-selected candidate scored below the confidence
    # threshold (LOW_CONFIDENCE_THRESHOLD in icdo3_extractor.py). The pick is
    # likely wrong; downstream consumers should treat the code as needing
    # user review and not auto-resolve diagnoses from it.
    low_confidence: bool = False


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
    # How the few-shot examples in the prompt were selected. "faiss" = semantic
    # nearest-neighbour retrieval; "static" = first-k from the flat store, which
    # happens when FAISS is unavailable and is NOT equivalent; "none" = zero-shot.
    # Recorded per result so a run's retrieval mode is auditable after the fact.
    fewshot_source: Optional[str] = None
    fewshot_count: Optional[int] = None


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
    clinical_context: Optional[Dict[str, Any]] = None  # Clinical context classification (initial_diagnosis/recurrence/progression/follow_up/mixed/unknown)


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
    # Prompts that were selected but are mapped to no report type in this batch,
    # so they ran on no note and produced nothing. Reported because the per-note
    # view cannot show it and the omission is otherwise silent.
    unpaired_prompt_types: Optional[List[str]] = None


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


# ---------------------------------------------------------------------------
# Study review (patient-level validation of a fixed study variable set)
# ---------------------------------------------------------------------------

class StudyVariableCandidate(BaseModel):
    """One value proposed by the LLM for a study variable, with its source.

    Carries enough to let a reviewer compare candidates: the value, its source
    note, the LLM reasoning, and the evidence spans to highlight in that note.
    """
    value: str
    note_id: str
    prompt_type: str = ""
    report_type: str = ""
    date: Optional[str] = None            # normalized date used for date-based resolution
    date_from: str = "event"              # "event" (LLM extracted the date) | "note" (fell back to the note's date) | "none"
    is_negated: Optional[bool] = None
    has_flags: bool = False               # hallucination / low-confidence present
    reasoning: Optional[str] = None       # LLM chain-of-thought for this value
    annotation_text: Optional[str] = None  # the raw annotation string (short evidence)
    evidence_spans: List[EvidenceSpan] = []  # spans into the source note for highlighting


class StudyVariableReview(BaseModel):
    """Per-patient validation state for a single study variable."""
    key: str
    label: str = ""
    source: str = "annotation"            # "annotation" | "diagnosis"
    proposed_value: Optional[str] = None  # value suggested by the resolver/rule
    value: Optional[str] = None           # human-confirmed value (None until confirmed)
    # auto         -> single unanimous value, no human action yet
    # needs_review -> conflict the rules could not settle / missing value
    # confirmed    -> a value is accepted (by a human, or auto-confirmed by a rule)
    # rejected     -> reviewer marked this variable as not exportable
    status: str = "needs_review"
    conflict: bool = False
    candidates: List[StudyVariableCandidate] = []
    source_note_ids: List[str] = []
    source_prompt_type: Optional[str] = None  # the session prompt_type key used
    evidence_snippet: Optional[str] = None
    reasoning: Optional[str] = None
    # Diagnosis-part code correction (histology / topography): the LLM's label is
    # trusted, its code is not — reviewers pick a real code from the condition file.
    llm_label: Optional[str] = None       # the descriptive text the LLM extracted
    llm_code: Optional[str] = None        # the (often hallucinated) code the LLM gave
    selected_code: Optional[str] = None   # the reviewer-selected real code
    combination_valid: Optional[bool] = None  # for the combination: is the pair in the diagnosis CSV
    # LLM-vs-human evaluation: the LLM's original proposed value, captured once at
    # resolve time and never overwritten, so accept-vs-edit stays recoverable after
    # a human confirms; review_action = the human's decision relative to it.
    llm_value: Optional[str] = None
    review_action: Optional[str] = None   # "accept" | "edit" | "reject" | None (not human-reviewed)
    # Auto conflict-resolution provenance
    auto_resolved: bool = False           # True when a rule (not a human) set the value
    resolution_rule: Optional[str] = None  # e.g. "report_type_ranking", "date_earliest"
    review_reasons: List[str] = []
    # Audit
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    note: Optional[str] = None


class CohortEligibility(BaseModel):
    """Auto-proposed + human-confirmed study-cohort membership for a patient."""
    decision: str = "needs_review"        # "included" | "excluded" | "needs_review"
    auto_decision: str = "needs_review"   # what the rule proposed
    confirmed: bool = False               # True once a reviewer confirms
    reasons: List[str] = []
    criteria: Dict[str, Any] = {}         # {histology: true/false/None, topography: ..., treatment: ...}
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None


class StudyTimelineEvent(BaseModel):
    """One dated point on a patient's clinical timeline (diagnosis anchor,
    disease-status change, metastasis, or treatment), assembled from the
    resolved study variables. Kept deliberately minimal (date + label only)."""
    date: Optional[str] = None            # DD/MM/YYYY (may be a note-date fallback — see date_from)
    date_from: str = "event"              # "event" | "note" | "none" (note = date is the note's date, not an extracted event date)
    category: str                         # "diagnosis" | "status" | "metastasis" | "treatment"
    label: str                            # short label, e.g. "Diagnosis", "Recurrence", "Metastasis", "Surgery"
    detail: Optional[str] = None          # optional short detail, e.g. metastatic sites or diagnosis code
    confirmed: bool = False               # True when the underlying study variable was human-confirmed (not LLM/auto)
    reviewed_by: Optional[str] = None     # who confirmed it (when confirmed)
    variable_key: str = ""                # study variable this event came from (for linking back)


class StudyEpisodeEvent(BaseModel):
    """One reviewer-curated outcome event (EpisodeEvent + linked DiseaseExtent):
    a recurrence/progression with its date and metastatic sites. Assembled from
    the LLM annotations, then confirmed / edited / dropped / added by the reviewer."""
    key: str                              # stable id for matching across recomputes
    disease_status: str                   # "recurrence" | "progression"
    date: Optional[str] = None            # DD/MM/YYYY (may be a note-date fallback)
    date_from: str = "event"              # "event" | "note" | "none"
    sites: List[str] = []                 # DiseaseExtent field names that are true (distant sites / localised)
    source_note_ids: List[str] = []
    origin: str = "llm"                   # "llm" (assembled) | "manual" (reviewer-added; an LLM miss)
    status: str = "proposed"              # "proposed" | "confirmed" | "dropped"
    edited: bool = False                  # a human changed the date/sites/status from the LLM assembly
    evidence_changed: bool = False        # confirmed event whose underlying annotation moved on re-run
    before_diagnosis: bool = False        # event date precedes the diagnosis — anomalous, verify (over-derived or historical)
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_action: Optional[str] = None   # "accept" | "edit" | "reject" | "missed" | None
    evidence: List[StudyVariableCandidate] = []  # source note(s) + LLM output that produced this event


class StudyPatientReview(BaseModel):
    """All study-review state for one patient."""
    patient_id: str
    eligibility: CohortEligibility = CohortEligibility()
    variables: Dict[str, StudyVariableReview] = {}
    events: List[StudyEpisodeEvent] = []     # curated longitudinal outcome events
    timeline: List[StudyTimelineEvent] = []  # chronological clinical timeline (diagnosis -> status/metastasis/treatments)
    # pending -> nothing confirmed; in_progress -> some confirmed; completed -> all confirmed
    overall_status: str = "pending"


class ConflictVariableConfig(BaseModel):
    """Per-variable automatic conflict-resolution strategy."""
    # "none"               -> conflicts always go to manual review (default)
    # "report_type_ranking"-> pick value from the highest-ranked report type present
    # "date"               -> pick value by date (earliest by default)
    strategy: str = "none"
    ranking: List[str] = []               # ordered report_type names (highest priority first)
    date_pref: str = "earliest"           # "earliest" | "latest"


class ConflictConfig(BaseModel):
    """Session-scoped automatic conflict-resolution settings for a study."""
    enabled: bool = False                 # master toggle (opt-in)
    per_variable: Dict[str, ConflictVariableConfig] = {}


class InclusionCodeRef(BaseModel):
    """One ICD-O code that is part of the study's cohort inclusion criteria."""
    code: str
    label: str = ""


class StudyInclusionCriteria(BaseModel):
    """The cohort inclusion ICD-O codes, surfaced so reviewers can see them while
    accepting/rejecting diagnosis codes in the review view."""
    histology_label: str = ""
    histology: List[InclusionCodeRef] = []       # morphology prefixes (e.g. 8850 Liposarcoma)
    topography_label: str = ""
    topography: List[InclusionCodeRef] = []       # topography codes (e.g. C48.0 Retroperitoneum)


class StudyReviewReport(BaseModel):
    """Study-review status across all patients in a session."""
    study_id: str
    study_name: str = ""
    condition_family: Optional[str] = None  # condition-file family for code search (e.g. 'sarc')
    inclusion_criteria: StudyInclusionCriteria = StudyInclusionCriteria()
    variables: List[Dict[str, Any]] = []  # variable definitions (key, label, source, type)
    report_types: List[str] = []          # report types present in the session
    conflict_config: ConflictConfig = ConflictConfig()
    patients: List[StudyPatientReview] = []
    total_patients: int = 0
    included: int = 0
    excluded: int = 0
    needs_review: int = 0


class StudyEvaluationStat(BaseModel):
    """Human-review outcome counts for the LLM's proposals on one variable (or
    the overall total). accept ~ LLM value kept as-is; edit ~ human corrected the
    value; reject ~ LLM value judged not usable (a false positive)."""
    key: str
    label: str = ""
    prompt_type: Optional[str] = None
    group: str = ""
    accept: int = 0
    edit: int = 0
    reject: int = 0
    missed: int = 0                        # LLM proposed nothing, human supplied it (false negative)
    reviewed: int = 0                      # accept + edit + reject + missed (human decisions counted)
    accept_rate: float = 0.0
    edit_rate: float = 0.0
    reject_rate: float = 0.0
    missed_rate: float = 0.0


class StudyEvaluationReport(BaseModel):
    """LLM-vs-human evaluation for a session's study review: how often reviewers
    accept / edit / reject the model's proposed values, overall and per variable."""
    study_id: str
    study_name: str = ""
    overall: StudyEvaluationStat = StudyEvaluationStat(key="__overall__", label="All variables")
    per_variable: List[StudyEvaluationStat] = []
    reviewed_patients: int = 0            # patients with at least one human decision
    total_patients: int = 0


class StudyVariableConfirmRequest(BaseModel):
    """Confirm / edit / reject a single study variable for a patient."""
    value: Optional[str] = None
    action: str = "confirm"               # "confirm" | "reject"
    reviewer: Optional[str] = None
    note: Optional[str] = None


class StudyEligibilityRequest(BaseModel):
    """Confirm cohort eligibility for a patient."""
    decision: str                         # "included" | "excluded"
    reviewer: Optional[str] = None


class StudyEventActionRequest(BaseModel):
    """Curate a patient's outcome-event list from the interactive timeline."""
    action: str                           # confirm_all | confirm | drop | restore | edit | add
    key: Optional[str] = None             # target event (confirm/drop/restore/edit)
    date: Optional[str] = None            # DD/MM/YYYY (edit/add)
    disease_status: Optional[str] = None  # recurrence | progression (edit/add)
    sites: Optional[List[str]] = None     # DiseaseExtent field names (edit/add)
    reviewer: Optional[str] = None


class StudyConflictConfigRequest(BaseModel):
    """Update the session-scoped conflict-resolution config for a study."""
    config: ConflictConfig


class CodeSearchResult(BaseModel):
    """A ranked morphology/topography code candidate from a condition file."""
    code: str
    label: str
    score: float
    source: str = ""


class CodeSearchResponse(BaseModel):
    results: List[CodeSearchResult] = []
    query: str = ""


class SetDiagnosisPartRequest(BaseModel):
    """Set the reviewer-chosen real code for one diagnosis part (histology or
    topography). When both parts are set the combination is validated + assembled."""
    part: str                              # "histology" | "topography"
    action: str = "select"                 # "select" | "reject"
    code: Optional[str] = None
    label: Optional[str] = None
    reviewer: Optional[str] = None


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

class ConflictSource(BaseModel):
    value: str
    note_id: str
    prompt_type: str


class ExportConflict(BaseModel):
    patient_id: str
    core_variable: str
    date_ref: Optional[str] = None  # None for non-repeatable entities
    conflicting_values: List[str]
    conflict_type: str  # "non_repeatable" | "repeatable_same_date"
    sources: List[ConflictSource] = []


class ExportValidationResponse(BaseModel):
    valid: bool
    conflicts: List[ExportConflict] = []
    row_count: int = 0
    deduplicated_count: int = 0


class ConflictResolveEntry(BaseModel):
    """Identifies a single annotation entry to remove when resolving conflicts."""
    note_id: str
    prompt_type: str


class ConflictResolveRequest(BaseModel):
    """Batch-delete annotation entries that are blocking export."""
    entries: List[ConflictResolveEntry]


class ConflictResolveResponse(BaseModel):
    deleted_count: int
    not_found_count: int
    remaining_conflicts: List[ExportConflict] = []
    valid: bool = False
    row_count: int = 0


class ExcludedRowSummary(BaseModel):
    patient_id: str = ""
    variable: str = ""
    value: str = ""
    reason: str = ""


class DiagnosisWarning(BaseModel):
    patient_id: str
    reasons: List[str] = []


class ExportMetadataResponse(BaseModel):
    """Side-channel metadata for a CSV export.

    Previously these lists were sent as the `X-Excluded-Rows` and
    `X-Diagnosis-Warnings` response headers on `/export` and
    `/export/codes`. For sessions with many conflicts those headers grew
    past reverse-proxy header buffer limits, so the data now lives in a
    dedicated endpoint and the CSV responses carry only `Content-Disposition`.
    """
    excluded_rows: List[ExcludedRowSummary] = []
    diagnosis_warnings: List[DiagnosisWarning] = []

