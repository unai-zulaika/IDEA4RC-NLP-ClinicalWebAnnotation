"""
Annotation processing routes
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from pathlib import Path
import sys
import time
import re

# Import from local modules
from services.vllm_client import get_vllm_client
from typing import Tuple

try:
    from lib.fewshot_builder import FewshotBuilder, map_annotation_to_prompt
except ImportError as e:
    print(f"[WARN] Could not import fewshot_builder: {e}")
    FewshotBuilder = None
    map_annotation_to_prompt = None

try:
    from lib.evaluation_engine import extract_structured_values
except ImportError as e:
    print(f"[WARN] Could not import evaluation_engine: {e}")
    def extract_structured_values(text):
        return {'dates': [], 'numbers_with_units': [], 'key_value_pairs': [], 'enumerations': []}

try:
    from services.evaluation_service import (
        evaluate_annotation_with_special_cases,
        evaluate_annotation_with_template,
        get_field_level_summary
    )
    EVALUATION_SERVICE_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] Could not import evaluation_service: {e}")
    import traceback
    traceback.print_exc()
    evaluate_annotation_with_special_cases = None
    evaluate_annotation_with_template = None
    get_field_level_summary = None
    EVALUATION_SERVICE_AVAILABLE = False
from models.schemas import (
    ProcessNoteRequest, ProcessNoteResponse, BatchProcessRequest, BatchProcessResponse,
    AnnotationResult, AnnotationValue, EvidenceSpan,
    ICDO3SearchResult, ICDO3SearchResponse, ICDO3ValidationResult,
    UnifiedICDO3Code, ICDO3CombineRequest, ICDO3CombineResponse
)

router = APIRouter()

# Initialize fewshot builder (lazy initialization)
_fewshot_builder: Optional[Any] = None  # Optional[FewshotBuilder] but avoid importing type
_prompts_loaded = False


# Global prompts storage (avoid importing model_runner which requires llama_cpp)
_PROMPTS: Dict[str, Any] = {}
_PROMPTS_DIR_MTIMES: Dict[str, float] = {}  # Track per-center file modification times

def _ensure_prompts_loaded(force_reload: bool = False):
    """Load prompts from directory-based structure without importing model_runner."""
    global _prompts_loaded, _PROMPTS, _PROMPTS_DIR_MTIMES
    from lib.prompt_adapter import adapt_all_prompts

    backend_dir = Path(__file__).parent.parent
    prompts_dir = backend_dir / "data" / "latest_prompts"

    # Check if any center file has been modified
    files_changed = False
    if prompts_dir.is_dir():
        for center_dir in prompts_dir.iterdir():
            if not center_dir.is_dir():
                continue
            prompts_file = center_dir / "prompts.json"
            if prompts_file.exists():
                current_mtime = prompts_file.stat().st_mtime
                prev_mtime = _PROMPTS_DIR_MTIMES.get(center_dir.name, 0.0)
                if current_mtime > prev_mtime:
                    files_changed = True
                    _PROMPTS_DIR_MTIMES[center_dir.name] = current_mtime

    if not _prompts_loaded or force_reload or files_changed:
        adapted_prompts = adapt_all_prompts(prompts_dir)
        _PROMPTS.clear()
        _PROMPTS.update(adapted_prompts)
        _prompts_loaded = True
        if files_changed or force_reload:
            print(f"[INFO] Loaded {len(_PROMPTS)} prompts from {prompts_dir}: {list(_PROMPTS.keys())}")


def _is_simple_prompt(template: str) -> bool:
    """
    Check if a prompt is a simple completion prompt (not structured annotation).
    
    Args:
        template: Prompt template string
    
    Returns:
        True if this is a simple prompt that shouldn't use structured JSON output
    """
    return (
        len(template.strip()) < 100 and  # Very short prompt
        "JSON" not in template and  # No JSON mentioned
        "structured" not in template.lower() and  # No structured format mentioned
        "evidence" not in template.lower() and  # No evidence field mentioned
        "reasoning" not in template.lower() and  # No reasoning field mentioned
        "### Input:" not in template and  # No structured input section
        "Now process" not in template.lower()  # No structured processing instructions
    )


def _get_prompt(task_key: str, fewshots: List[Tuple[str, str]], note_text: str, csv_date: Optional[str] = None) -> str:
    """
    Build prompt from template (standalone version, doesn't require model_runner).
    Now includes JSON format instructions for structured output.
    
    Args:
        task_key: Prompt type key
        fewshots: List of (note_text, annotation) tuples
        note_text: The note to process
        csv_date: Optional CSV date column value
    
    Returns:
        Formatted prompt string with JSON format instructions
    """
    _ensure_prompts_loaded()
    
    if task_key not in _PROMPTS:
        raise KeyError(f"No prompt found for task '{task_key}'. Known: {list(_PROMPTS.keys())}")
    
    template = _PROMPTS[task_key]["template"]
    
    # Format fewshots
    fewshots_text = ""
    if fewshots:
        fewshots_parts = []
        for note, annotation in fewshots:
            fewshots_parts.append(f"Example:\n- Medical Note: {note}\n- Annotation: {annotation}")
        fewshots_text = "\n\n---\n\n".join(fewshots_parts)
    
    # Replace placeholders - handle both formats for compatibility
    prompt = template.replace("{few_shot_examples}", fewshots_text)
    prompt = prompt.replace("{fewshots}", fewshots_text)  # Also support model_runner format
    prompt = prompt.replace("{static_samples}", "")  # Remove static samples placeholder if present
    
    # Replace note and date placeholders first
    from lib.prompt_wrapper import wrap_prompt_with_json_format, update_prompt_placeholders
    prompt = update_prompt_placeholders(prompt, note_text, csv_date)
    
    # Only wrap with JSON format instructions if the prompt doesn't already have them
    # and if it's not a simple test prompt (check if it contains structured output instructions)
    is_simple = _is_simple_prompt(template)
    
    if not is_simple:
        # Wrap with JSON format instructions for structured annotation prompts
        prompt = wrap_prompt_with_json_format(prompt, csv_date)
    
    return prompt


# Simple few-shot storage (CSV-based, no FAISS required)
_simple_fewshots: Dict[str, List[Tuple[str, str]]] = {}  # prompt_type -> [(note, annotation), ...]

def _get_fewshots_file() -> Path:
    """Get path to few-shot examples storage file"""
    backend_dir = Path(__file__).parent.parent
    data_dir = backend_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "fewshots.json"

def _load_fewshots_from_disk() -> Dict[str, List[Tuple[str, str]]]:
    """Load few-shot examples from disk"""
    fewshots_file = _get_fewshots_file()
    if not fewshots_file.exists():
        return {}
    
    try:
        import json
        with open(fewshots_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Convert from JSON format (list of lists) to list of tuples
        result = {}
        for prompt_type, examples in data.items():
            result[prompt_type] = [(ex[0], ex[1]) for ex in examples]
        return result
    except Exception as e:
        print(f"[WARN] Failed to load fewshots from disk: {e}")
        return {}

def _load_fewshots_on_startup():
    """Load few-shot examples from disk on startup"""
    try:
        fewshots = _load_fewshots_from_disk()
        if fewshots:
            _simple_fewshots.update(fewshots)
            total = sum(len(examples) for examples in fewshots.values())
            print(f"[INFO] Loaded {total} few-shot examples from disk ({len(fewshots)} prompt types)")
    except Exception as e:
        print(f"[WARN] Failed to load fewshots on startup: {e}")

# Load fewshots from disk on module import
_load_fewshots_on_startup()

def _get_fewshot_builder():
    """Get or create fewshot builder (FAISS-based, optional)"""
    global _fewshot_builder
    if FewshotBuilder is None:
        return None  # Return None instead of raising - allows zero-shot mode
    
    if _fewshot_builder is None:
        try:
            backend_dir = Path(__file__).parent.parent
            faiss_dir = backend_dir / "data" / "faiss_store"
            # Note: JSON file should be provided by user or copied to data directory
            # For now, we'll skip auto-building and rely on pre-built indexes or CSV uploads
            json_file = backend_dir / "data" / "annotated_patient_notes_with_spans_full_verified.json"
            if not json_file.exists():
                json_file = backend_dir / "data" / "annotated_patient_notes.json"
            
            _fewshot_builder = FewshotBuilder(store_dir=faiss_dir, use_gpu=True)
            
            # Build indexes if needed and JSON file exists
            if json_file.exists():
                if not (faiss_dir / "gender-int.index").exists():
                    prompts_dir = backend_dir / "data" / "latest_prompts"
                    if prompts_dir.is_dir():
                        _fewshot_builder.build_all_int_prompts(
                            json_file,
                            prompts_dir,
                            patient_indices=[8, 9],
                            force_rebuild=False
                        )
                else:
                    # Preload indexes
                    _ensure_prompts_loaded()
                    prompt_types = list(_PROMPTS.keys())
                    _fewshot_builder.preload_all_indexes(prompt_types)
            else:
                # Try to preload existing indexes even without JSON file
                _ensure_prompts_loaded()
                prompt_types = list(_PROMPTS.keys())
                _fewshot_builder.preload_all_indexes(prompt_types)
        except Exception as e:
            print(f"[ERROR] Failed to initialize FewshotBuilder: {e}")
            _fewshot_builder = None
            print(f"[WARN] Continuing in zero-shot mode (no few-shot examples)")
            return None
    
    return _fewshot_builder


def _get_fewshot_examples(prompt_type: str, note_text: str, k: int = 5) -> List[Tuple[str, str]]:
    """
    Get few-shot examples using either FAISS builder or simple storage.
    Returns empty list if none available (zero-shot mode).
    """
    # Try FAISS builder first (if available)
    builder = _get_fewshot_builder()
    if builder is not None:
        try:
            examples = builder.get_fewshot_examples(prompt_type, note_text, k=k)
            if examples:
                return examples
        except Exception as e:
            print(f"[WARN] FAISS few-shot retrieval failed: {e}, falling back to simple storage")
    
    # Fallback to simple storage
    if prompt_type in _simple_fewshots:
        examples = _simple_fewshots[prompt_type]
        # Simple similarity: return first k examples (could be enhanced with embeddings)
        return examples[:k]
    
    # No few-shots available - zero-shot mode
    return []


def _normalize_text(text: str) -> str:
    """Normalize text for matching: lowercase, remove extra whitespace, handle accents"""
    import unicodedata
    # Convert to lowercase
    text = text.lower()
    # Normalize unicode (NFD = decomposed form, then remove combining marks)
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _find_evidence_in_text(note_text: str, evidence_text: str) -> Optional[Tuple[int, int]]:
    """
    Find evidence text in note text using normalized matching.
    Returns (start, end) if found, None otherwise.
    """
    if not evidence_text or not note_text:
        return None
    
    # Try exact match first (case-insensitive)
    evidence_lower = evidence_text.lower()
    note_lower = note_text.lower()
    start = note_lower.find(evidence_lower)
    if start != -1:
        return (start, start + len(evidence_text))
    
    # Try normalized match
    evidence_norm = _normalize_text(evidence_text)
    note_norm = _normalize_text(note_text)
    start_norm = note_norm.find(evidence_norm)
    if start_norm != -1:
        # Map back to original positions (approximate)
        # Count characters before match in normalized text
        char_count = 0
        orig_start = 0
        for i, char in enumerate(note_text):
            if char_count >= start_norm:
                orig_start = i
                break
            char_norm = _normalize_text(char)
            if char_norm:
                char_count += 1
        
        # Find end position
        orig_end = orig_start
        char_count_end = 0
        for i in range(orig_start, len(note_text)):
            if char_count_end >= len(evidence_norm):
                orig_end = i
                break
            char_norm = _normalize_text(note_text[i])
            if char_norm:
                char_count_end += 1
        
        return (orig_start, orig_end)
    
    # Try fuzzy matching: split evidence into words and find each word
    evidence_words = evidence_text.split()
    if len(evidence_words) > 0:
        # Find first word
        first_word = evidence_words[0].lower()
        start = note_lower.find(first_word)
        if start != -1:
            # Try to find the rest of the evidence starting from first word
            remaining_evidence = ' '.join(evidence_words[1:])
            if remaining_evidence:
                # Check if remaining text appears after first word
                check_start = start + len(first_word)
                if check_start < len(note_text):
                    remaining_note = note_text[check_start:check_start + len(evidence_text) + 50]
                    remaining_note_lower = remaining_note.lower()
                    remaining_evidence_lower = remaining_evidence.lower()
                    if remaining_evidence_lower in remaining_note_lower:
                        # Found it
                        end = check_start + remaining_note_lower.find(remaining_evidence_lower) + len(remaining_evidence)
                        return (start, end)
            else:
                # Only one word
                return (start, start + len(first_word))
    
    return None


def _extract_evidence_spans(note_text: str, evidence_text: str, prompt_type: str) -> List[EvidenceSpan]:
    """Extract evidence spans from evidence text using normalized matching"""
    spans = []
    
    if not evidence_text or not note_text:
        return spans
    
    # Try to find evidence in note text
    match = _find_evidence_in_text(note_text, evidence_text)
    if match:
        start, end = match
        # Extract the actual text from note (may differ slightly due to normalization)
        actual_text = note_text[start:end]
        spans.append(EvidenceSpan(
            start=start,
            end=end,
            text=actual_text,
            prompt_type=prompt_type
        ))
    
    return spans


def _parse_annotation_values(annotation_text: str, note_text: str, prompt_type: str) -> List[AnnotationValue]:
    """Parse annotation text into structured values"""
    # Extract structured values using evaluation_engine
    structured_values = extract_structured_values(annotation_text)
    
    values = []
    
    # Extract dates
    for date in structured_values.get('dates', []):
        values.append(AnnotationValue(
            value=date,
            evidence_spans=_extract_evidence_spans(note_text, annotation_text, prompt_type),
            reasoning=None
        ))
    
    # Extract enumerations
    for enum_val in structured_values.get('enumerations', []):
        values.append(AnnotationValue(
            value=enum_val,
            evidence_spans=_extract_evidence_spans(note_text, annotation_text, prompt_type),
            reasoning=None
        ))
    
    # Extract key-value pairs
    for key, val in structured_values.get('key_value_pairs', []):
        values.append(AnnotationValue(
            value=f"{key}: {val}",
            evidence_spans=_extract_evidence_spans(note_text, annotation_text, prompt_type),
            reasoning=None
        ))
    
    # If no structured values found, treat entire annotation as single value
    if not values:
        values.append(AnnotationValue(
            value=annotation_text,
            evidence_spans=_extract_evidence_spans(note_text, annotation_text, prompt_type),
            reasoning=None
        ))
    
    return values


@router.post("/process", response_model=ProcessNoteResponse)
async def process_note(request: ProcessNoteRequest, session_id: str, note_text: str):
    """Process a single note with selected prompts using structured generation"""
    _ensure_prompts_loaded()
    
    # Get vLLM client
    vllm_client = get_vllm_client()
    if not vllm_client.is_available():
        raise HTTPException(status_code=503, detail="VLLM server not available")
    
    # Get CSV date and session info (including evaluation mode) from session
    csv_date = None
    session_data = None
    evaluation_mode = "validation"
    report_type = None
    report_type_mapping = None
    try:
        import importlib.util
        sessions_path = Path(__file__).parent / "sessions.py"
        spec = importlib.util.spec_from_file_location("sessions", sessions_path)
        if spec and spec.loader:
            sessions_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sessions_module)
            session_data = sessions_module._load_session(session_id)
            evaluation_mode = session_data.get("evaluation_mode", "validation")
            report_type_mapping = session_data.get("report_type_mapping")
            # Find the note in session to get its date, report_type, and annotations
            for note in session_data.get("notes", []):
                if note.get("note_id") == request.note_id:
                    csv_date = note.get("date")
                    report_type = note.get("report_type")
                    break
    except Exception as e:
        print(f"[WARN] Could not load session: {e}")
    
    start_time = time.time()
    note_annotations = []
    
    # Filter prompt types based on report_type_mapping if available
    prompt_types_to_process = request.prompt_types
    if report_type_mapping and report_type:
        # Get allowed prompt types for this report type
        allowed_prompt_types = report_type_mapping.get(report_type, [])
        if allowed_prompt_types:
            # Filter to only process prompts that are allowed for this report type
            prompt_types_to_process = [pt for pt in request.prompt_types if pt in allowed_prompt_types]
            print(f"[INFO] Filtered prompts for report_type '{report_type}': {len(prompt_types_to_process)}/{len(request.prompt_types)} prompts will be processed")
        else:
            # If no mapping exists for this report type, don't process any prompts
            print(f"[INFO] No prompt types mapped for report_type '{report_type}', skipping all prompts")
            prompt_types_to_process = []
    
    # Try to use structured generation with Outlines
    try:
        from services.structured_generator import (
            generate_structured_annotation,
            generate_structured_annotation_fallback,
            OUTLINES_AVAILABLE
        )
        use_structured = OUTLINES_AVAILABLE
    except ImportError:
        use_structured = False
        print("[WARN] Structured generation not available, using fallback")
    
    # Process each prompt type
    for prompt_type in prompt_types_to_process:
        try:
            # Get fewshot examples
            if request.use_fewshots:
                fewshot_examples = _get_fewshot_examples(
                    prompt_type,
                    note_text,
                    k=request.fewshot_k
                )
            else:
                fewshot_examples = []
            
            # Build prompt (now includes JSON format instructions)
            prompt = _get_prompt(
                task_key=prompt_type,
                fewshots=fewshot_examples,
                note_text=note_text,
                csv_date=csv_date
            )
            
            # Always store the raw prompt for debugging
            raw_prompt = prompt
            print(f"[DEBUG] Prompt for {prompt_type} (length: {len(prompt)}): {prompt[:300]}...")
            
            # Check if this is a simple prompt (no structured output needed)
            template = _PROMPTS[prompt_type]["template"]
            is_simple = _is_simple_prompt(template)
            
            # Generate structured annotation
            raw_response = None
            if is_simple:
                # For simple prompts, just get raw output without structured parsing
                output = vllm_client.generate(
                    prompt=prompt,
                    max_new_tokens=512,
                    temperature=0.0,  # Deterministic output
                    return_logprobs=False
                )
                # Use "raw" output, not "normalized" (normalized only takes first line)
                raw_output = output.get("raw", output.get("normalized", ""))
                raw_response = raw_output
                print(f"[DEBUG] Simple prompt raw output: {raw_output[:200]}")
                
                # Clean up the output - remove special tokens and extra reasoning
                cleaned_output = raw_output.strip()
                # Remove special tokens like <unused94>thought at the start
                cleaned_output = re.sub(r'^<unused\d+>\w+\s*', '', cleaned_output, flags=re.IGNORECASE)
                # Remove any "The user wants me to..." type reasoning that models sometimes add
                cleaned_output = re.sub(r'^(The user wants me to|I need to|They have provided).*?\.\s*', '', cleaned_output, flags=re.IGNORECASE | re.DOTALL)
                cleaned_output = cleaned_output.strip()
                
                # If cleaned output is empty or very short, use original
                if not cleaned_output or len(cleaned_output) < 5:
                    cleaned_output = raw_output.strip()
                
                # Create a simple structured annotation from raw output
                from models.annotation_models import StructuredAnnotation
                structured_ann = StructuredAnnotation(
                    evidence="",
                    reasoning="Simple completion prompt - no structured parsing applied",
                    final_output=cleaned_output,
                    is_negated=False,
                    date=None
                )
                # Normalize absence indicators to standard format
                from lib.annotation_normalizer import normalize_annotation_output
                annotation_text = normalize_annotation_output(
                    structured_ann.final_output,
                    prompt_type=prompt_type,
                    normalize_absence=True
                )
                reasoning = structured_ann.reasoning
                evidence = structured_ann.evidence
                is_negated = structured_ann.is_negated
                date_info = structured_ann.date
            elif use_structured:
                try:
                    structured_ann, raw_response = generate_structured_annotation(
                        prompt=prompt,
                        vllm_endpoint=vllm_client.config["vllm_endpoint"],
                        model_name=vllm_client.config["model_name"],
                        csv_date=csv_date,
                        max_new_tokens=1024,  # Increased for longer reasoning
                        temperature=0.0  # Deterministic output
                    )
                    
                    # Extract annotation text from structured output
                    # Normalize absence indicators to standard format
                    from lib.annotation_normalizer import normalize_annotation_output
                    annotation_text = normalize_annotation_output(
                        structured_ann.final_output,
                        prompt_type=prompt_type,
                        normalize_absence=True
                    )
                    reasoning = structured_ann.reasoning
                    evidence = structured_ann.evidence
                    is_negated = structured_ann.is_negated
                    date_info = structured_ann.date
                    
                except Exception as e:
                    print(f"[WARN] Structured generation failed for {prompt_type}: {e}, using fallback")
                    import traceback
                    traceback.print_exc()
                    # Fallback to regular generation
                    output = vllm_client.generate(
                        prompt=prompt,
                        max_new_tokens=512,
                        temperature=0.1,
                        return_logprobs=False
                    )
                    # Use "raw" output, not "normalized" (normalized only takes first line)
                    raw_output = output.get("raw", output.get("normalized", ""))
                    raw_response = raw_output
                    print(f"[DEBUG] Raw LLM output for {prompt_type} (length: {len(raw_output)}): {raw_output[:500]}")
                    structured_ann = generate_structured_annotation_fallback(
                        prompt=prompt,
                        raw_output=raw_output,
                        csv_date=csv_date
                    )
                    # Normalize absence indicators to standard format
                    from lib.annotation_normalizer import normalize_annotation_output
                    annotation_text = normalize_annotation_output(
                        structured_ann.final_output,
                        prompt_type=prompt_type,
                        normalize_absence=True
                    )
                    reasoning = structured_ann.reasoning
                    evidence = structured_ann.evidence
                    is_negated = structured_ann.is_negated
                    date_info = structured_ann.date
                    print(f"[DEBUG] Parsed annotation_text: {annotation_text[:200] if annotation_text else 'EMPTY'}")
            else:
                # Fallback: regular generation
                output = vllm_client.generate(
                    prompt=prompt,
                    max_new_tokens=512,
                    temperature=0.0,  # Deterministic output
                    return_logprobs=False
                )
                # Use "raw" output, not "normalized" (normalized only takes first line)
                raw_output = output.get("raw", output.get("normalized", ""))
                raw_response = raw_output
                print(f"[DEBUG] Fallback raw LLM output for {prompt_type} (length: {len(raw_output)}): {raw_output[:500]}")
                structured_ann = generate_structured_annotation_fallback(
                    prompt=prompt,
                    raw_output=raw_output,
                    csv_date=csv_date
                )
                # Normalize absence indicators to standard format
                from lib.annotation_normalizer import normalize_annotation_output
                annotation_text = normalize_annotation_output(
                    structured_ann.final_output,
                    prompt_type=prompt_type,
                    normalize_absence=True
                )
                reasoning = structured_ann.reasoning
                evidence = structured_ann.evidence
                is_negated = structured_ann.is_negated
                date_info = structured_ann.date
                
                # Clean annotation (remove "Annotation: " prefix if present)
                annotation_text = re.sub(r'^\s*annotation\s*:\s*', '', annotation_text, flags=re.IGNORECASE).strip()
            
            # Extract evidence spans from evidence field using improved matching
            evidence_spans = _extract_evidence_spans(note_text, evidence, prompt_type)
            
            # Parse into values
            values = _parse_annotation_values(annotation_text, note_text, prompt_type)
            
            # Extract ICD-O-3 codes for histology/site prompts
            icdo3_code_info = None
            try:
                from lib.icdo3_extractor import extract_icdo3_from_text, is_histology_or_site_prompt
                if is_histology_or_site_prompt(prompt_type):
                    print(f"[INFO] Extracting ICD-O-3 code for prompt_type={prompt_type}, annotation_length={len(annotation_text)}, note_length={len(note_text) if note_text else 0}")
                    # Pass both annotation text and note text for better extraction
                    # Also pass vLLM client for LLM-based extraction
                    icdo3_code_info = extract_icdo3_from_text(
                        annotation_text, 
                        prompt_type, 
                        note_text=note_text,
                        vllm_client=vllm_client
                    )
                    if icdo3_code_info:
                        print(f"[INFO] Successfully extracted ICD-O-3 code: {icdo3_code_info.get('code')}, query_code={icdo3_code_info.get('query_code')}, match_method={icdo3_code_info.get('match_method')}")
                        # Convert to Pydantic model if needed
                        from models.schemas import ICDO3CodeInfo
                        if isinstance(icdo3_code_info, dict):
                            icdo3_code_info = ICDO3CodeInfo(**icdo3_code_info)
                    else:
                        print(f"[WARN] No ICD-O-3 code extracted for {prompt_type} (extraction returned None)")
            except Exception as e:
                print(f"[ERROR] Failed to extract ICD-O-3 code for {prompt_type}: {e}")
                import traceback
                traceback.print_exc()
            
            # Convert date_info to dict if it's a Pydantic model
            date_info_dict = None
            if date_info:
                if hasattr(date_info, 'dict'):
                    date_info_dict = date_info.dict()
                elif isinstance(date_info, dict):
                    date_info_dict = date_info
                else:
                    date_info_dict = {
                        "date_value": getattr(date_info, 'date_value', None),
                        "source": getattr(date_info, 'source', None),
                        "csv_date": getattr(date_info, 'csv_date', None)
                    }
            
            # Fallback: If date_info is None but csv_date is available, use csv_date
            if not date_info_dict and csv_date:
                date_info_dict = {
                    "date_value": csv_date,
                    "source": "derived_from_csv",
                    "csv_date": csv_date
                }
            
            # Determine status: check if annotation is incomplete or failed
            status = "success"
            if annotation_text.startswith("ERROR:"):
                status = "error"
            elif reasoning and (reasoning.endswith("...") or len(reasoning) > 900):  # Likely truncated
                status = "incomplete"
            elif not annotation_text or annotation_text.strip() == "":
                # Check if empty because information is not available (vs actual error)
                # If reasoning indicates "not available", "unknown", "not mentioned", etc., it's a valid "no annotation" case
                if reasoning:
                    reasoning_lower = reasoning.lower()
                    no_info_indicators = [
                        "not available", "not mentioned", "not stated", "not provided",
                        "unknown", "cannot be determined", "cannot be determined from",
                        "does not state", "does not provide", "does not mention",
                        "information is not available", "no information", "not found"
                    ]
                    if any(indicator in reasoning_lower for indicator in no_info_indicators):
                        # This is a valid "no annotation" case, not an error
                        status = "success"
                    else:
                        status = "error"
                else:
                    status = "error"
            
            # Evaluate annotation if in evaluation mode
            evaluation_result = None
            if evaluation_mode == "evaluation":
                if not EVALUATION_SERVICE_AVAILABLE or not evaluate_annotation_with_special_cases:
                    print(f"[WARN] Evaluation mode enabled but evaluation_service not available")
                elif not session_data:
                    print(f"[WARN] Evaluation mode enabled but session_data not loaded")
                else:
                    # Get expected annotation for this note and prompt type
                    expected_annotation = None
                    for note in session_data.get("notes", []):
                        if note.get("note_id") == request.note_id:
                            annotations_str = note.get("annotations")
                            if annotations_str:
                                # Try to extract expected annotation using pattern matching
                                # Use a more robust pattern that captures everything until the next prompt_type or end of string
                                # First, split by pipe to get individual annotation parts
                                parts = str(annotations_str).split('|')
                                for part in parts:
                                    part = part.strip()
                                    # Check if this part starts with the prompt type
                                    if ':' in part:
                                        # Split on first colon
                                        key_part, value_part = part.split(':', 1)
                                        key_part = key_part.strip()
                                        # Check if the key matches (case-insensitive, handle variations)
                                        if prompt_type.lower() in key_part.lower() or key_part.lower() in prompt_type.lower():
                                            expected_annotation = value_part.strip()
                                            break
                                # Fallback: try regex if split didn't work
                                if not expected_annotation:
                                    pattern = re.compile(rf'{re.escape(prompt_type)}\s*:\s*([^|]+)', re.IGNORECASE | re.DOTALL)
                                    match = pattern.search(str(annotations_str))
                                    if match:
                                        expected_annotation = match.group(1).strip()
                            break
                    
                    # Perform evaluation (even if expected_annotation is None - means no annotation expected)
                    try:
                        # Get template for field-level evaluation
                        template = None
                        if prompt_type in _PROMPTS:
                            prompt_info = _PROMPTS[prompt_type]
                            if isinstance(prompt_info, dict):
                                template = prompt_info.get("template", "")
                            else:
                                template = prompt_info

                        # Use template-aware evaluation if template available
                        if template and evaluate_annotation_with_template:
                            evaluation_result = evaluate_annotation_with_template(
                                expected=expected_annotation or "",
                                predicted=annotation_text,
                                template=template,
                                note_id=request.note_id,
                                prompt_type=prompt_type
                            )
                        else:
                            evaluation_result = evaluate_annotation_with_special_cases(
                                expected=expected_annotation or "",
                                predicted=annotation_text,
                                note_id=request.note_id,
                                prompt_type=prompt_type
                            )
                        print(f"[DEBUG] Evaluation result for {prompt_type}: overall_match={evaluation_result.get('overall_match')}, similarity={evaluation_result.get('similarity_score')}, field_eval={evaluation_result.get('field_evaluation', {}).get('field_evaluation_available', False)}")
                    except Exception as e:
                        print(f"[ERROR] Failed to evaluate annotation: {e}")
                        import traceback
                        traceback.print_exc()
            
            # Convert ICD-O-3 code to dict if it's a Pydantic model
            icdo3_code_dict = None
            if icdo3_code_info:
                if hasattr(icdo3_code_info, 'dict'):
                    icdo3_code_dict = icdo3_code_info.dict()
                elif isinstance(icdo3_code_info, dict):
                    icdo3_code_dict = icdo3_code_info
                else:
                    icdo3_code_dict = {
                        "code": getattr(icdo3_code_info, 'code', None),
                        "topography_code": getattr(icdo3_code_info, 'topography_code', None),
                        "morphology_code": getattr(icdo3_code_info, 'morphology_code', None),
                        "histology_code": getattr(icdo3_code_info, 'histology_code', None),
                        "behavior_code": getattr(icdo3_code_info, 'behavior_code', None),
                        "description": getattr(icdo3_code_info, 'description', None),
                        "confidence": getattr(icdo3_code_info, 'confidence', None),
                        "query_code": getattr(icdo3_code_info, 'query_code', None),
                        "match_method": getattr(icdo3_code_info, 'match_method', None),
                        "match_score": getattr(icdo3_code_info, 'match_score', None)
                    }
            
            note_annotations.append(AnnotationResult(
                prompt_type=prompt_type,
                annotation_text=annotation_text,
                values=values,
                confidence_score=None,
                evidence_spans=evidence_spans,
                reasoning=reasoning,
                is_negated=is_negated,
                date_info=date_info_dict,
                evidence_text=evidence,  # Store raw evidence text
                raw_prompt=raw_prompt if 'raw_prompt' in locals() else prompt,  # Store raw prompt
                raw_response=raw_response if raw_response is not None else "No response generated",  # Store raw response
                status=status,
                evaluation_result=evaluation_result,  # Store evaluation results
                icdo3_code=icdo3_code_dict  # Store ICD-O-3 code information
            ))
            
        except Exception as e:
            print(f"[ERROR] Failed to process {prompt_type}: {e}")
            import traceback
            traceback.print_exc()
            # Always capture raw prompt and response even on error
            error_prompt = prompt if 'prompt' in locals() else "Prompt not available"
            error_response = raw_response if 'raw_response' in locals() and raw_response else f"Error occurred: {str(e)}"
            note_annotations.append(AnnotationResult(
                prompt_type=prompt_type,
                annotation_text=f"ERROR: {str(e)}",
                values=[],
                evidence_spans=[],
                reasoning=None,
                is_negated=None,
                date_info=None,
                evidence_text=None,
                raw_prompt=error_prompt,
                raw_response=error_response,
                status="error"
            ))
    
    return ProcessNoteResponse(
        note_id=request.note_id,
        note_text=note_text,
        annotations=note_annotations,
        processing_time_seconds=time.time() - start_time
    )


@router.post("/batch", response_model=BatchProcessResponse)
async def batch_process(request: BatchProcessRequest, session_id: str = Query(...)):
    """Batch process multiple notes"""
    _ensure_prompts_loaded()
    
    # Load session - import here to avoid circular dependency
    import importlib.util
    sessions_path = Path(__file__).parent / "sessions.py"
    spec = importlib.util.spec_from_file_location("sessions", sessions_path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail="Failed to load sessions module")
    sessions_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sessions_module)
    
    try:
        session = sessions_module._load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    
    # Get evaluation mode from session (default to validation if not set)
    evaluation_mode = session.get('evaluation_mode', 'validation')
    print(f"[DEBUG] Batch processing: evaluation_mode={evaluation_mode}")
    
    # Get vLLM client
    vllm_client = get_vllm_client()
    if not vllm_client.is_available():
        # Get status for better error message
        status = vllm_client.get_status()
        error_detail = status.get("error", "Unknown error")
        endpoint = vllm_client.config.get("vllm_endpoint", "not configured")
        raise HTTPException(
            status_code=503, 
            detail=f"VLLM server not available. Endpoint: {endpoint}, Error: {error_detail}. "
                   f"Please ensure the VLLM server is running and restart the backend if you moved the project directory."
        )
    
    # Get CSV dates for notes and evaluation mode
    note_dates = {}
    report_type_mapping = session.get('report_type_mapping')
    evaluation_mode = session.get('evaluation_mode', 'validation')
    for note in session.get('notes', []):
        note_dates[note.get('note_id')] = note.get('date')
    
    # Try to use structured generation with Outlines
    try:
        from services.structured_generator import (
            generate_structured_annotation,
            generate_structured_annotation_fallback,
            OUTLINES_AVAILABLE
        )
        use_structured = OUTLINES_AVAILABLE
    except ImportError:
        use_structured = False
        print("[WARN] Structured generation not available, using fallback")
    
    # Process each note
    results = []
    start_time = time.time()
    
    for note_id in request.note_ids:
        # Find note in session
        note_data = None
        for note in session['notes']:
            if note['note_id'] == note_id:
                note_data = note
                break
        
        if not note_data:
            continue
        
        note_text = note_data['text']
        csv_date = note_dates.get(note_id)
        report_type = note_data.get('report_type')
        note_annotations = []
        
        # Filter prompt types based on report_type_mapping if available
        prompt_types_to_process = request.prompt_types
        if report_type_mapping and report_type:
            # Get allowed prompt types for this report type
            allowed_prompt_types = report_type_mapping.get(report_type, [])
            if allowed_prompt_types:
                # Filter to only process prompts that are allowed for this report type
                prompt_types_to_process = [pt for pt in request.prompt_types if pt in allowed_prompt_types]
            else:
                # If no mapping exists for this report type, don't process any prompts
                prompt_types_to_process = []
        
        # Process each prompt type
        for prompt_type in prompt_types_to_process:
            prompt_start = time.time()
            
            try:
                # Get fewshot examples
                if request.use_fewshots:
                    fewshot_examples = _get_fewshot_examples(
                        prompt_type,
                        note_text,
                        k=request.fewshot_k
                    )
                else:
                    fewshot_examples = []
                
                # Build prompt (now includes JSON format instructions)
                prompt = _get_prompt(
                    task_key=prompt_type,
                    fewshots=fewshot_examples,
                    note_text=note_text,
                    csv_date=csv_date
                )
                
                # Always store the raw prompt for debugging
                raw_prompt = prompt
                print(f"[DEBUG] Prompt for {prompt_type} (length: {len(prompt)}): {prompt[:300]}...")
                
                # Check if this is a simple prompt (no structured output needed)
                template = _PROMPTS[prompt_type]["template"]
                is_simple = _is_simple_prompt(template)
                
                # Generate structured annotation
                raw_response = None
                if is_simple:
                    # For simple prompts, just get raw output without structured parsing
                    output = vllm_client.generate(
                        prompt=prompt,
                        max_new_tokens=512,
                        temperature=0.1,
                        return_logprobs=False
                    )
                    # Use "raw" output, not "normalized" (normalized only takes first line)
                    raw_output = output.get("raw", output.get("normalized", ""))
                    raw_response = raw_output
                    print(f"[DEBUG] Simple prompt raw output: {raw_output[:200]}")
                    
                    # Clean up the output - remove special tokens and extra reasoning
                    cleaned_output = raw_output.strip()
                    # Remove special tokens like <unused94>thought at the start
                    cleaned_output = re.sub(r'^<unused\d+>\w+\s*', '', cleaned_output, flags=re.IGNORECASE)
                    # Remove any "The user wants me to..." type reasoning that models sometimes add
                    cleaned_output = re.sub(r'^(The user wants me to|I need to|They have provided).*?\.\s*', '', cleaned_output, flags=re.IGNORECASE | re.DOTALL)
                    cleaned_output = cleaned_output.strip()
                    
                    # If cleaned output is empty or very short, use original
                    if not cleaned_output or len(cleaned_output) < 5:
                        cleaned_output = raw_output.strip()
                    
                    # Create a simple structured annotation from raw output
                    from models.annotation_models import StructuredAnnotation
                    structured_ann = StructuredAnnotation(
                        evidence="",
                        reasoning="Simple completion prompt - no structured parsing applied",
                        final_output=cleaned_output,
                        is_negated=False,
                        date=None
                    )
                    # Normalize absence indicators to standard format
                    from lib.annotation_normalizer import normalize_annotation_output
                    annotation_text = normalize_annotation_output(
                        structured_ann.final_output,
                        prompt_type=prompt_type,
                        normalize_absence=True
                    )
                    reasoning = structured_ann.reasoning
                    evidence = structured_ann.evidence
                    is_negated = structured_ann.is_negated
                    date_info = structured_ann.date
                elif use_structured:
                    try:
                        structured_ann, raw_response = generate_structured_annotation(
                            prompt=prompt,
                            vllm_endpoint=vllm_client.config["vllm_endpoint"],
                            model_name=vllm_client.config["model_name"],
                            csv_date=csv_date,
                            max_new_tokens=1024,  # Increased for longer reasoning
                            temperature=0.1
                        )
                        
                        # Extract annotation text from structured output
                        # Normalize absence indicators to standard format
                        from lib.annotation_normalizer import normalize_annotation_output
                        annotation_text = normalize_annotation_output(
                            structured_ann.final_output,
                            prompt_type=prompt_type,
                            normalize_absence=True
                        )
                        reasoning = structured_ann.reasoning
                        evidence = structured_ann.evidence
                        is_negated = structured_ann.is_negated
                        date_info = structured_ann.date
                        
                    except Exception as e:
                        print(f"[WARN] Structured generation failed for {prompt_type}: {e}, using fallback")
                        import traceback
                        traceback.print_exc()
                        # Fallback to regular generation
                        output = vllm_client.generate(
                            prompt=prompt,
                            max_new_tokens=512,
                            temperature=0.1,
                            return_logprobs=False
                        )
                        # Use "raw" output, not "normalized" (normalized only takes first line)
                        raw_output = output.get("raw", output.get("normalized", ""))
                        raw_response = raw_output
                        print(f"[DEBUG] Fallback raw LLM output for {prompt_type} (length: {len(raw_output)}): {raw_output[:500]}")
                        structured_ann = generate_structured_annotation_fallback(
                            prompt=prompt,
                            raw_output=raw_output,
                            csv_date=csv_date
                        )
                        # Normalize absence indicators to standard format
                        from lib.annotation_normalizer import normalize_annotation_output
                        annotation_text = normalize_annotation_output(
                            structured_ann.final_output,
                            prompt_type=prompt_type,
                            normalize_absence=True
                        )
                        reasoning = structured_ann.reasoning
                        evidence = structured_ann.evidence
                        is_negated = structured_ann.is_negated
                        date_info = structured_ann.date
                else:
                    # Fallback: regular generation
                    output = vllm_client.generate(
                        prompt=prompt,
                        max_new_tokens=512,
                        temperature=0.1,
                        return_logprobs=False
                    )
                    # Use "raw" output, not "normalized" (normalized only takes first line)
                    raw_output = output.get("raw", output.get("normalized", ""))
                    raw_response = raw_output
                    print(f"[DEBUG] Fallback raw LLM output for {prompt_type} (length: {len(raw_output)}): {raw_output[:500]}")
                    structured_ann = generate_structured_annotation_fallback(
                        prompt=prompt,
                        raw_output=raw_output,
                        csv_date=csv_date
                    )
                    # Normalize absence indicators to standard format
                    from lib.annotation_normalizer import normalize_annotation_output
                    annotation_text = normalize_annotation_output(
                        structured_ann.final_output,
                        prompt_type=prompt_type,
                        normalize_absence=True
                    )
                    reasoning = structured_ann.reasoning
                    evidence = structured_ann.evidence
                    is_negated = structured_ann.is_negated
                    date_info = structured_ann.date
                
                # Clean annotation (remove "Annotation: " prefix if present)
                annotation_text = re.sub(r'^\s*annotation\s*:\s*', '', annotation_text, flags=re.IGNORECASE).strip()
                
                # Extract evidence spans from evidence field using improved matching
                evidence_spans = _extract_evidence_spans(note_text, evidence, prompt_type)
                
                # Parse into values
                values = _parse_annotation_values(annotation_text, note_text, prompt_type)
                
                # Extract ICD-O-3 codes for histology/site prompts
                icdo3_code_info = None
                try:
                    from lib.icdo3_extractor import extract_icdo3_from_text, is_histology_or_site_prompt
                    if is_histology_or_site_prompt(prompt_type):
                        print(f"[INFO] Extracting ICD-O-3 code for prompt_type={prompt_type}, note_id={note_id}, annotation_length={len(annotation_text)}, note_length={len(note_text) if note_text else 0}")
                        # Pass both annotation text and note text for better extraction
                        # Also pass vLLM client for LLM-based extraction
                        icdo3_code_info = extract_icdo3_from_text(
                            annotation_text, 
                            prompt_type, 
                            note_text=note_text,
                            vllm_client=vllm_client
                        )
                        if icdo3_code_info:
                            print(f"[INFO] Successfully extracted ICD-O-3 code for {prompt_type} (note {note_id}): code={icdo3_code_info.get('code')}, query_code={icdo3_code_info.get('query_code')}, match_method={icdo3_code_info.get('match_method')}")
                            # Convert to Pydantic model if needed
                            from models.schemas import ICDO3CodeInfo
                            if isinstance(icdo3_code_info, dict):
                                icdo3_code_info = ICDO3CodeInfo(**icdo3_code_info)
                        else:
                            print(f"[WARN] No ICD-O-3 code extracted for {prompt_type} (note {note_id}) - extraction returned None")
                except Exception as e:
                    print(f"[ERROR] Failed to extract ICD-O-3 code for {prompt_type} (note {note_id}): {e}")
                    import traceback
                    traceback.print_exc()
                
                # Convert date_info to dict if it's a Pydantic model
                date_info_dict = None
                if date_info:
                    if hasattr(date_info, 'dict'):
                        date_info_dict = date_info.dict()
                    elif isinstance(date_info, dict):
                        date_info_dict = date_info
                    else:
                        date_info_dict = {
                            "date_value": getattr(date_info, 'date_value', None),
                            "source": getattr(date_info, 'source', None),
                            "csv_date": getattr(date_info, 'csv_date', None)
                        }
                
                # Fallback: If date_info is None but csv_date is available, use csv_date
                if not date_info_dict and csv_date:
                    date_info_dict = {
                        "date_value": csv_date,
                        "source": "derived_from_csv",
                        "csv_date": csv_date
                    }
                
                # Convert ICD-O-3 code to dict if it's a Pydantic model
                icdo3_code_dict = None
                if icdo3_code_info:
                    if hasattr(icdo3_code_info, 'dict'):
                        icdo3_code_dict = icdo3_code_info.dict()
                    elif isinstance(icdo3_code_info, dict):
                        icdo3_code_dict = icdo3_code_info
                    else:
                        icdo3_code_dict = {
                            "code": getattr(icdo3_code_info, 'code', None),
                            "topography_code": getattr(icdo3_code_info, 'topography_code', None),
                            "morphology_code": getattr(icdo3_code_info, 'morphology_code', None),
                            "histology_code": getattr(icdo3_code_info, 'histology_code', None),
                            "behavior_code": getattr(icdo3_code_info, 'behavior_code', None),
                            "description": getattr(icdo3_code_info, 'description', None),
                            "confidence": getattr(icdo3_code_info, 'confidence', None),
                            "query_code": getattr(icdo3_code_info, 'query_code', None),
                            "match_method": getattr(icdo3_code_info, 'match_method', None),
                            "match_score": getattr(icdo3_code_info, 'match_score', None)
                        }
                
                # Determine status: check if annotation is incomplete or failed
                status = "success"
                if annotation_text.startswith("ERROR:"):
                    status = "error"
                elif reasoning and (reasoning.endswith("...") or len(reasoning) > 900):  # Likely truncated
                    status = "incomplete"
                elif not annotation_text or annotation_text.strip() == "":
                    # Check if empty because information is not available (vs actual error)
                    # If reasoning indicates "not available", "unknown", "not mentioned", etc., it's a valid "no annotation" case
                    if reasoning:
                        reasoning_lower = reasoning.lower()
                        no_info_indicators = [
                            "not available", "not mentioned", "not stated", "not provided",
                            "unknown", "cannot be determined", "cannot be determined from",
                            "does not state", "does not provide", "does not mention",
                            "information is not available", "no information", "not found"
                        ]
                        if any(indicator in reasoning_lower for indicator in no_info_indicators):
                            # This is a valid "no annotation" case, not an error
                            status = "success"
                        else:
                            status = "error"
                    else:
                        status = "error"
                
                # Evaluate annotation if in evaluation mode
                evaluation_result = None
                if evaluation_mode == "evaluation":
                    if not EVALUATION_SERVICE_AVAILABLE or not evaluate_annotation_with_special_cases:
                        print(f"[WARN] Evaluation mode enabled but evaluation_service not available")
                    else:
                        # Get expected annotation for this note and prompt type
                        expected_annotation = None
                        if note_data:
                            annotations_str = note_data.get("annotations")
                            if annotations_str:
                                # Use a more robust extraction: split by pipe first
                                parts = str(annotations_str).split('|')
                                for part in parts:
                                    part = part.strip()
                                    # Check if this part starts with the prompt type
                                    if ':' in part:
                                        # Split on first colon
                                        key_part, value_part = part.split(':', 1)
                                        key_part = key_part.strip()
                                        # Check if the key matches (case-insensitive, handle variations)
                                        if prompt_type.lower() in key_part.lower() or key_part.lower() in prompt_type.lower():
                                            expected_annotation = value_part.strip()
                                            break
                                # Fallback: try regex if split didn't work
                                if not expected_annotation:
                                    pattern = re.compile(rf'{re.escape(prompt_type)}\s*:\s*([^|]+)', re.IGNORECASE | re.DOTALL)
                                    match = pattern.search(str(annotations_str))
                                    if match:
                                        expected_annotation = match.group(1).strip()
                        
                        # Perform evaluation (even if expected_annotation is None - means no annotation expected)
                        try:
                            # Get template for field-level evaluation
                            template = None
                            if prompt_type in _PROMPTS:
                                prompt_info = _PROMPTS[prompt_type]
                                if isinstance(prompt_info, dict):
                                    template = prompt_info.get("template", "")
                                else:
                                    template = prompt_info

                            # Use template-aware evaluation if template available
                            if template and evaluate_annotation_with_template:
                                evaluation_result = evaluate_annotation_with_template(
                                    expected=expected_annotation or "",
                                    predicted=annotation_text,
                                    template=template,
                                    note_id=note_id,
                                    prompt_type=prompt_type
                                )
                            else:
                                evaluation_result = evaluate_annotation_with_special_cases(
                                    expected=expected_annotation or "",
                                    predicted=annotation_text,
                                    note_id=note_id,
                                    prompt_type=prompt_type
                                )
                            print(f"[DEBUG] Evaluation result for {prompt_type} (note {note_id}): overall_match={evaluation_result.get('overall_match')}, similarity={evaluation_result.get('similarity_score')}, field_eval={evaluation_result.get('field_evaluation', {}).get('field_evaluation_available', False)}")
                        except Exception as e:
                            print(f"[ERROR] Failed to evaluate annotation: {e}")
                            import traceback
                            traceback.print_exc()

                note_annotations.append(AnnotationResult(
                    prompt_type=prompt_type,
                    annotation_text=annotation_text,
                    values=values,
                    confidence_score=None,
                    evidence_spans=evidence_spans,
                    reasoning=reasoning,
                    is_negated=is_negated,
                    date_info=date_info_dict,
                    evidence_text=evidence,
                    raw_prompt=raw_prompt if 'raw_prompt' in locals() else prompt,
                    raw_response=raw_response if raw_response is not None else "No response generated",
                    status=status,
                    evaluation_result=evaluation_result,  # Store evaluation results
                    icdo3_code=icdo3_code_dict  # Store ICD-O-3 code information
                ))
                
            except Exception as e:
                print(f"[ERROR] Failed to process {prompt_type} for {note_id}: {e}")
                import traceback
                traceback.print_exc()
                # Always capture raw prompt and response even on error
                error_prompt = prompt if 'prompt' in locals() else "Prompt not available"
                error_response = raw_response if 'raw_response' in locals() and raw_response else f"Error occurred: {str(e)}"
                # Add error annotation
                note_annotations.append(AnnotationResult(
                    prompt_type=prompt_type,
                    annotation_text=f"ERROR: {str(e)}",
                    values=[],
                    evidence_spans=[],
                    reasoning=None,
                    is_negated=None,
                    date_info=None,
                    evidence_text=None,
                    raw_prompt=error_prompt,
                    raw_response=error_response,
                    status="error"
                ))
        
        results.append(ProcessNoteResponse(
            note_id=note_id,
            note_text=note_text,
            annotations=note_annotations,
            processing_time_seconds=time.time() - prompt_start if note_annotations else 0
        ))
    
    return BatchProcessResponse(
        results=results,
        total_time_seconds=time.time() - start_time
    )


@router.post("/icdo3/select")
async def select_icdo3_candidate(
    session_id: str = Query(..., description="Session ID"),
    note_id: str = Query(..., description="Note ID"),
    prompt_type: str = Query(..., description="Prompt type (must be histology/site prompt)"),
    candidate_index: int = Query(..., ge=0, le=4, description="Index of candidate to select (0-4)")
):
    """
    Update the selected ICD-O-3 candidate for an annotation.

    This endpoint allows users to select a different candidate from the list
    of 5 candidates returned during annotation processing.

    Args:
        session_id: Session ID
        note_id: Note ID
        prompt_type: Prompt type (must be a histology/site prompt)
        candidate_index: Index of candidate to select (0-4)

    Returns:
        Updated icdo3_code with new selection
    """
    # Load session
    import importlib.util
    sessions_path = Path(__file__).parent / "sessions.py"
    spec = importlib.util.spec_from_file_location("sessions", sessions_path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail="Failed to load sessions module")
    sessions_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sessions_module)

    try:
        session = sessions_module._load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Get annotation for this note and prompt type
    annotations = session.get('annotations', {})
    note_annotations = annotations.get(note_id, {})
    annotation = note_annotations.get(prompt_type)

    if not annotation:
        raise HTTPException(status_code=404, detail=f"Annotation not found for note_id={note_id}, prompt_type={prompt_type}")

    # Get ICD-O-3 code info
    icdo3_code = annotation.get('icdo3_code')
    if not icdo3_code:
        raise HTTPException(status_code=400, detail="No ICD-O-3 code information available for this annotation")

    candidates = icdo3_code.get('candidates', [])
    if not candidates:
        raise HTTPException(status_code=400, detail="No ICD-O-3 candidates available for selection")

    if candidate_index >= len(candidates):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid candidate index: {candidate_index}. Only {len(candidates)} candidates available."
        )

    # Get the selected candidate
    selected = candidates[candidate_index]

    # Update the icdo3_code with the selection
    icdo3_code['selected_candidate_index'] = candidate_index
    icdo3_code['user_selected'] = True
    icdo3_code['code'] = selected['query_code']
    icdo3_code['query_code'] = selected['query_code']
    icdo3_code['morphology_code'] = selected.get('morphology_code')
    icdo3_code['topography_code'] = selected.get('topography_code')
    icdo3_code['description'] = selected.get('name')
    icdo3_code['match_score'] = selected.get('match_score')
    icdo3_code['match_method'] = f"user_selected_{selected.get('match_method', 'unknown')}"

    # Parse morphology code for histology and behavior codes
    morphology_code = selected.get('morphology_code', '')
    if morphology_code and '/' in morphology_code:
        parts = morphology_code.split('/')
        icdo3_code['histology_code'] = parts[0]
        icdo3_code['behavior_code'] = parts[1] if len(parts) > 1 else None

    # Update the annotation
    annotation['icdo3_code'] = icdo3_code
    session['annotations'][note_id][prompt_type] = annotation

    # Save session
    sessions_module._save_session(session_id, session)

    print(f"[INFO] Updated ICD-O-3 selection for note={note_id}, prompt={prompt_type}: candidate_index={candidate_index}, code={selected['query_code']}")

    return {
        "success": True,
        "icdo3_code": icdo3_code,
        "message": f"Selected candidate {candidate_index + 1}: {selected['query_code']} - {selected.get('name', '')}"
    }


@router.get("/icdo3/search", response_model=ICDO3SearchResponse)
async def search_icdo3_codes(
    q: str = Query(..., min_length=1, description="Search query (name or code)"),
    morphology: Optional[str] = Query(None, description="Filter by morphology code prefix"),
    topography: Optional[str] = Query(None, description="Filter by topography code prefix"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of results")
):
    """
    Search ICD-O-3 diagnosis codes by text or code.

    Searches the NAME column and code fields for matches.
    Supports filtering by morphology or topography code prefix.

    Args:
        q: Search query string
        morphology: Optional morphology code filter (e.g., "8031" or "8031/3")
        topography: Optional topography code filter (e.g., "C00" or "C00.2")
        limit: Maximum number of results (default 20)

    Returns:
        List of matching ICD-O-3 codes with match scores
    """
    try:
        from lib.icdo3_csv_indexer import get_csv_indexer

        indexer = get_csv_indexer()
        if indexer is None:
            raise HTTPException(status_code=503, detail="ICD-O-3 CSV indexer not available")

        results = indexer.search_by_text(
            query=q,
            morphology_filter=morphology,
            topography_filter=topography,
            limit=limit
        )

        # Convert to response model
        search_results = [
            ICDO3SearchResult(
                query_code=r['query_code'],
                morphology_code=r['morphology_code'],
                topography_code=r['topography_code'],
                name=r['name'],
                match_score=r['match_score']
            )
            for r in results
        ]

        return ICDO3SearchResponse(
            results=search_results,
            total_count=len(search_results),
            query=q,
            morphology_filter=morphology,
            topography_filter=topography
        )

    except Exception as e:
        print(f"[ERROR] ICD-O-3 search failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/icdo3/validate", response_model=ICDO3ValidationResult)
async def validate_icdo3_combination(
    morphology: str = Query(..., description="Morphology code (e.g., '8031/3')"),
    topography: str = Query(..., description="Topography code (e.g., 'C00.2')")
):
    """
    Validate if a morphology + topography combination exists in the ICD-O-3 CSV.

    Args:
        morphology: Morphology code (e.g., "8031/3")
        topography: Topography code (e.g., "C00.2")

    Returns:
        Validation result with matched query code and name if valid
    """
    try:
        from lib.icdo3_csv_indexer import get_csv_indexer

        indexer = get_csv_indexer()
        if indexer is None:
            raise HTTPException(status_code=503, detail="ICD-O-3 CSV indexer not available")

        result = indexer.validate_combination(morphology, topography)

        return ICDO3ValidationResult(
            valid=result['valid'],
            query_code=result.get('query_code'),
            name=result.get('name'),
            morphology_valid=result['morphology_valid'],
            topography_valid=result['topography_valid']
        )

    except Exception as e:
        print(f"[ERROR] ICD-O-3 validation failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")


@router.post("/icdo3/combine", response_model=ICDO3CombineResponse)
async def combine_icdo3_code(
    session_id: str = Query(..., description="Session ID"),
    note_id: str = Query(..., description="Note ID"),
    request: ICDO3CombineRequest = None
):
    """
    Save a unified ICD-O-3 code for a note (combining histology and topography).

    This endpoint stores the selected unified code in the session's unified_icdo3_codes field.

    Args:
        session_id: Session ID
        note_id: Note ID
        request: Request body containing the query_code to save

    Returns:
        Success status and the saved unified code
    """
    if request is None:
        raise HTTPException(status_code=400, detail="Request body is required")

    try:
        from lib.icdo3_csv_indexer import get_csv_indexer
        from datetime import datetime

        # Load session
        import importlib.util
        sessions_path = Path(__file__).parent / "sessions.py"
        spec = importlib.util.spec_from_file_location("sessions", sessions_path)
        if spec is None or spec.loader is None:
            raise HTTPException(status_code=500, detail="Failed to load sessions module")
        sessions_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sessions_module)

        try:
            session = sessions_module._load_session(session_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        # Validate the query code exists in CSV
        indexer = get_csv_indexer()
        if indexer is None:
            raise HTTPException(status_code=503, detail="ICD-O-3 CSV indexer not available")

        query_code = request.query_code.strip()
        if query_code not in indexer.query_index:
            raise HTTPException(status_code=400, detail=f"Invalid query code: {query_code}")

        # Get the row data
        row = indexer.query_index[query_code]
        morphology_code = str(row.get('Morphology', '')).strip()
        topography_code = str(row.get('Topography', '')).strip()
        name = str(row.get('NAME', '')).strip()

        # Create unified code object
        unified_code = UnifiedICDO3Code(
            query_code=query_code,
            morphology_code=morphology_code,
            topography_code=topography_code,
            name=name,
            source="user_override",
            user_selected=True,
            validation={
                'morphology_valid': True,
                'topography_valid': True,
                'combination_valid': True
            },
            created_at=datetime.utcnow()
        )

        # Initialize unified_icdo3_codes if not present
        if 'unified_icdo3_codes' not in session:
            session['unified_icdo3_codes'] = {}

        # Save the unified code for this note
        session['unified_icdo3_codes'][note_id] = unified_code.dict()

        # Save session
        sessions_module._save_session(session_id, session)

        print(f"[INFO] Saved unified ICD-O-3 code for session={session_id}, note={note_id}: {query_code}")

        return ICDO3CombineResponse(
            success=True,
            unified_code=unified_code,
            message=f"Saved unified code: {query_code} - {name}"
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] ICD-O-3 combine failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to save unified code: {str(e)}")


@router.get("/icdo3/topographies")
async def get_valid_topographies(
    morphology: str = Query(..., description="Morphology code (e.g., '8031/3')"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of results")
):
    """
    Get valid topography codes for a given morphology code.

    Args:
        morphology: Morphology code
        limit: Maximum number of results

    Returns:
        List of valid topography codes with their query codes and names
    """
    try:
        from lib.icdo3_csv_indexer import get_csv_indexer

        indexer = get_csv_indexer()
        if indexer is None:
            raise HTTPException(status_code=503, detail="ICD-O-3 CSV indexer not available")

        results = indexer.get_valid_topographies_for_morphology(morphology, limit)

        return {
            "morphology": morphology,
            "topographies": results,
            "count": len(results)
        }

    except Exception as e:
        print(f"[ERROR] Get valid topographies failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get topographies: {str(e)}")


@router.get("/icdo3/morphologies")
async def get_valid_morphologies(
    topography: str = Query(..., description="Topography code (e.g., 'C00.2')"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of results")
):
    """
    Get valid morphology codes for a given topography code.

    Args:
        topography: Topography code
        limit: Maximum number of results

    Returns:
        List of valid morphology codes with their query codes and names
    """
    try:
        from lib.icdo3_csv_indexer import get_csv_indexer

        indexer = get_csv_indexer()
        if indexer is None:
            raise HTTPException(status_code=503, detail="ICD-O-3 CSV indexer not available")

        results = indexer.get_valid_morphologies_for_topography(topography, limit)

        return {
            "topography": topography,
            "morphologies": results,
            "count": len(results)
        }

    except Exception as e:
        print(f"[ERROR] Get valid morphologies failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get morphologies: {str(e)}")


@router.get("/icdo3/unified/{note_id}")
async def get_unified_icdo3_code(
    session_id: str = Query(..., description="Session ID"),
    note_id: str = None
):
    """
    Get the unified ICD-O-3 code for a note if one has been saved.

    Args:
        session_id: Session ID
        note_id: Note ID (from path)

    Returns:
        The unified code if exists, or null
    """
    try:
        # Load session
        import importlib.util
        sessions_path = Path(__file__).parent / "sessions.py"
        spec = importlib.util.spec_from_file_location("sessions", sessions_path)
        if spec is None or spec.loader is None:
            raise HTTPException(status_code=500, detail="Failed to load sessions module")
        sessions_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sessions_module)

        try:
            session = sessions_module._load_session(session_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        unified_codes = session.get('unified_icdo3_codes', {})
        unified_code = unified_codes.get(note_id)

        return {
            "note_id": note_id,
            "unified_code": unified_code,
            "exists": unified_code is not None
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Get unified ICD-O-3 code failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get unified code: {str(e)}")

