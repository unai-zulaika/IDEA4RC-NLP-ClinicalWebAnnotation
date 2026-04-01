"""
Annotation processing routes
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from pathlib import Path
import asyncio
import os
import sys
import time
import re

# Import from local modules
from services.vllm_client import get_vllm_client
from lib.timing import TimingBreakdown
from lib.note_chunker import NoteChunker
from lib.history_detector import get_history_detector
from lib.note_splitter import split_history_note, build_sub_note, get_cached_split
from lib.result_aggregator import aggregate_results as aggregate_multi_value_results
from models.schemas import ChunkInfo
from models.annotation_models import NoteSplitResult
from typing import Tuple

# Configurable concurrency for parallel vLLM calls
VLLM_CONCURRENCY = int(os.environ.get("VLLM_CONCURRENCY", "2"))
_vllm_semaphore = asyncio.Semaphore(VLLM_CONCURRENCY)

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
    UnifiedICDO3Code, ICDO3CombineRequest, ICDO3CombineResponse,
    SequentialProcessRequest, SequentialNoteResult, SequentialProcessResponse
)

router = APIRouter()

# Initialize fewshot builder (lazy initialization)
_fewshot_builder: Optional[Any] = None  # Optional[FewshotBuilder] but avoid importing type
_prompts_loaded = False


# Global prompts storage (avoid importing model_runner which requires llama_cpp)
_PROMPTS: Dict[str, Any] = {}
_PROMPTS_DIR_MTIMES: Dict[str, float] = {}  # Track per-center file modification times

# Fast prompts storage (condensed prompts for fast mode)
_FAST_PROMPTS: Dict[str, Any] = {}
_FAST_PROMPTS_LOADED = False
_FAST_PROMPTS_DIR_MTIMES: Dict[str, float] = {}

# Entity cardinality cache (0 = repeatable, 1 = non-repeatable)
_ENTITY_CARDINALITY: Optional[Dict[str, int]] = None


def _load_entity_cardinality() -> Dict[str, int]:
    """Load entity cardinality config (lazy, cached)."""
    global _ENTITY_CARDINALITY
    if _ENTITY_CARDINALITY is None:
        import json as _json
        path = Path(__file__).resolve().parent.parent / "data" / "entities_cardinality.json"
        with open(path) as f:
            _ENTITY_CARDINALITY = _json.load(f)
    return _ENTITY_CARDINALITY


def _is_repeatable_entity(prompt_type: str) -> bool:
    """Check if a prompt type's entity is repeatable (cardinality 0).

    Uses the entity_mapping from prompt config to find the entity type,
    then checks against entities_cardinality.json.
    """
    cardinality = _load_entity_cardinality()

    # Look up entity_mapping from either standard or fast prompts
    prompt_info = _PROMPTS.get(prompt_type, {})
    if not prompt_info:
        prompt_info = _FAST_PROMPTS.get(prompt_type, {})

    entity_mapping = prompt_info.get("entity_mapping", {})
    if not entity_mapping:
        return False

    entity_type = entity_mapping.get("entity_type", "")
    # entity_type can be "SystemicTreatment" or "Diagnosis.ageAtDiagnosis"
    base_entity = entity_type.split(".")[0] if entity_type else ""

    if not base_entity:
        return False

    return cardinality.get(base_entity, 1) == 0

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


def _ensure_fast_prompts_loaded(force_reload: bool = False):
    """Load fast prompts from backend/data/fast_prompts/ directory."""
    global _FAST_PROMPTS_LOADED, _FAST_PROMPTS, _FAST_PROMPTS_DIR_MTIMES
    from lib.prompt_adapter import adapt_all_prompts

    backend_dir = Path(__file__).parent.parent
    prompts_dir = backend_dir / "data" / "fast_prompts"

    if not prompts_dir.is_dir():
        _FAST_PROMPTS_LOADED = True
        return

    files_changed = False
    for center_dir in prompts_dir.iterdir():
        if not center_dir.is_dir():
            continue
        prompts_file = center_dir / "prompts.json"
        if prompts_file.exists():
            current_mtime = prompts_file.stat().st_mtime
            prev_mtime = _FAST_PROMPTS_DIR_MTIMES.get(center_dir.name, 0.0)
            if current_mtime > prev_mtime:
                files_changed = True
                _FAST_PROMPTS_DIR_MTIMES[center_dir.name] = current_mtime

    if not _FAST_PROMPTS_LOADED or force_reload or files_changed:
        adapted_prompts = adapt_all_prompts(prompts_dir)
        _FAST_PROMPTS.clear()
        _FAST_PROMPTS.update(adapted_prompts)
        _FAST_PROMPTS_LOADED = True
        if files_changed or force_reload:
            print(f"[INFO] Loaded {len(_FAST_PROMPTS)} fast prompts from {prompts_dir}: {list(_FAST_PROMPTS.keys())}")


def _get_applicable_prompts(
    note_id: str,
    requested_prompt_types: List[str],
    report_type: Optional[str],
    report_type_mapping: Optional[Dict],
    note_prompt_overrides: Dict,
    note_prompt_exclusions: Dict,
) -> List[str]:
    """Filter prompt types for a note based on report_type_mapping + overrides - exclusions."""
    if not report_type_mapping or not report_type:
        return requested_prompt_types
    allowed = set(report_type_mapping.get(report_type, []))
    allowed.update(note_prompt_overrides.get(note_id, []))
    allowed -= set(note_prompt_exclusions.get(note_id, []))
    if allowed:
        filtered = [pt for pt in requested_prompt_types if pt in allowed]
        print(f"[INFO] Filtered prompts for report_type '{report_type}': {len(filtered)}/{len(requested_prompt_types)} prompts will be processed")
        return filtered
    print(f"[INFO] No prompt types mapped for report_type '{report_type}', skipping all prompts")
    return []


def _annotation_result_to_dict(result, note_id: str, prompt_type: str) -> dict:
    """Convert an AnnotationResult from _process_single_prompt to session storage dict format."""
    return {
        "note_id": note_id,
        "prompt_type": prompt_type,
        "annotation_text": result.annotation_text,
        "values": [v.model_dump() for v in (result.values or [])],
        "edited": False,
        "is_negated": result.is_negated,
        "date_info": result.date_info,
        "evidence_text": result.evidence_text,
        "reasoning": result.reasoning,
        "raw_prompt": result.raw_prompt,
        "raw_response": result.raw_response,
        "evidence_spans": [s.model_dump() for s in (result.evidence_spans or [])],
        "status": result.status,
        "evaluation_result": result.evaluation_result,
        "icdo3_code": result.icdo3_code.model_dump() if result.icdo3_code else None,
        "chunk_info": result.chunk_info.model_dump() if result.chunk_info else None,
        "derived_field_values": getattr(result, 'derived_field_values', None),
        "hallucination_flags": [f.model_dump() for f in result.hallucination_flags] if result.hallucination_flags else None,
        "multi_value_info": result.multi_value_info if hasattr(result, 'multi_value_info') and result.multi_value_info else None,
    }


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


MAX_FEWSHOT_NOTE_CHARS = 500  # Truncate few-shot note text to avoid oversized prompts

# --- Fewshot sanitization (optional) ---
# Non-English prefixes that should be translated to English equivalents.
# Centers: INT-SARC/INT-HNC → Italian, VGR → Swedish, MSCI → Polish
_FEWSHOT_PREFIX_TRANSLATIONS = {
    # Italian (INT-SARC, INT-HNC)
    "tipo istologico:": "Histological type:",
    "tipo histologico:": "Histological type:",
    "sito del tumore": "Tumor site",
    "sito tumorale": "Tumor site",
    "margini dopo chirurgia": "Margins after surgery",
    "genere del paziente": "Patient's gender",
    "grading della biopsia": "Biopsy grading",
    "profondità del tumore": "Tumor depth",
    "tipo di recidiva": "Type of recurrence",
    "stato del paziente": "Status of the patient",
    "età alla diagnosi": "Age at diagnosis",
    "stadio alla diagnosi": "Stage at diagnosis",
    "tipo di chirurgia": "Surgery was performed",
    # Swedish (VGR)
    "histologisk typ:": "Histological type:",
    "tumörlokalisation": "Tumor site",
    "tumörplats": "Tumor site",
    # Polish (MSCI)
    "typ histologiczny:": "Histological type:",
    "lokalizacja guza": "Tumor site",
    "miejsce guza": "Tumor site",
}

# Placeholder patterns to remove from fewshot annotations (all languages)
_FEWSHOT_PLACEHOLDER_PATTERNS = [
    r'\(\[seleziona il codice ICD-O-3\]\)',     # Italian
    r'\(\[select ICD-O-3 code\]\)',              # English
    r'\(\[välj ICD-O-3-kod\]\)',                 # Swedish
    r'\(\[wybierz kod ICD-O-3\]\)',              # Polish
    r'\[seleziona il codice ICD-O-3\]',          # Italian (without parens)
    r'\[select ICD-O-3 code\]',                  # English (without parens)
    r'\[välj ICD-O-3-kod\]',                     # Swedish (without parens)
    r'\[wybierz kod ICD-O-3\]',                  # Polish (without parens)
    r'\(:\s*seleziona il codice ICD-O-3',        # Malformed Italian
    r'\(:\s*select ICD-O-3 code',                # Malformed English
    r'\[seleziona[^\]]*\]',                      # Generic Italian placeholder
    r'\[välj[^\]]*\]',                           # Generic Swedish placeholder
    r'\[wybierz[^\]]*\]',                        # Generic Polish placeholder
    r'\[select[^\]]*(?:code|tipo|type)[^\]]*\]', # Generic English code placeholder
    r'\[please select[^\]]*\]',                  # English "please select"
]
_FEWSHOT_PLACEHOLDER_RE = re.compile('|'.join(_FEWSHOT_PLACEHOLDER_PATTERNS), re.IGNORECASE)


def _sanitize_fewshot_annotation(annotation: str) -> str:
    """
    Sanitize a single fewshot annotation:
    1. Translate non-English prefixes to English
    2. Remove placeholder patterns (e.g., [select ICD-O-3 code])
    3. Clean up residual formatting artifacts

    Returns the cleaned annotation string.
    """
    result = annotation

    # Step 1: Translate non-English prefixes to English (case-insensitive)
    result_lower = result.lower()
    for foreign, english in _FEWSHOT_PREFIX_TRANSLATIONS.items():
        idx = result_lower.find(foreign)
        if idx != -1:
            result = result[:idx] + english + result[idx + len(foreign):]
            result_lower = result.lower()

    # Step 2: Remove placeholder patterns
    result = _FEWSHOT_PLACEHOLDER_RE.sub('', result)

    # Step 3: Clean up formatting artifacts
    result = re.sub(r'\(\s*\)', '', result)       # Empty parens ()
    result = re.sub(r'\(\s*:\s*\)', '', result)   # Malformed (: )
    result = re.sub(r'\s+\.', '.', result)         # Space before period
    result = re.sub(r'\s{2,}', ' ', result)       # Collapse multiple spaces
    result = result.strip().rstrip(',').strip()    # Trailing commas
    # Ensure trailing period
    if result and not result.endswith('.'):
        result += '.'

    return result


def _sanitize_fewshot_examples(
    fewshots: List[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    """
    Sanitize a list of fewshot examples by cleaning their annotation text.
    Removes examples that become empty after sanitization.

    Args:
        fewshots: List of (note_text, annotation) tuples

    Returns:
        Sanitized list of (note_text, annotation) tuples
    """
    sanitized = []
    for note, annotation in fewshots:
        cleaned = _sanitize_fewshot_annotation(annotation)
        if cleaned and len(cleaned) > 5:  # Skip if annotation is essentially empty
            sanitized.append((note, cleaned))
    return sanitized


def _get_prompt(task_key: str, fewshots: List[Tuple[str, str]], note_text: str, csv_date: Optional[str] = None, fast_mode: bool = False, use_guided_decoding: bool = False) -> str:
    """
    Build prompt from template (standalone version, doesn't require model_runner).
    Now includes JSON format instructions for structured output.

    Args:
        task_key: Prompt type key
        fewshots: List of (note_text, annotation) tuples
        note_text: The note to process
        csv_date: Optional CSV date column value
        fast_mode: Use condensed fast prompts (skip JSON wrapping and few-shots)

    Returns:
        Formatted prompt string with JSON format instructions
    """
    _ensure_prompts_loaded()

    # In fast mode, try fast prompts first, fall back to standard
    if fast_mode:
        _ensure_fast_prompts_loaded()
        if task_key in _FAST_PROMPTS:
            template = _FAST_PROMPTS[task_key]["template"]
            # Substitute few-shot examples if placeholder present
            if fewshots:
                fewshots_parts = []
                for note, annotation in fewshots:
                    truncated = note[:MAX_FEWSHOT_NOTE_CHARS] + "..." if len(note) > MAX_FEWSHOT_NOTE_CHARS else note
                    fewshots_parts.append(
                        f'Example:\n- Medical Note: {truncated}\n- Response: {{"final_output": "{annotation}"}}'
                    )
                fewshots_text = "\n\n---\n\n".join(fewshots_parts)
            else:
                fewshots_text = ""
            template = template.replace("{few_shot_examples}", fewshots_text)
            template = template.replace("{fewshots}", fewshots_text)
            from lib.prompt_wrapper import update_prompt_placeholders, wrap_prompt_with_json_format
            prompt = update_prompt_placeholders(template, note_text, csv_date)
            # When guided decoding is active, add concise JSON format instructions
            # so the model knows the semantic meaning of each field
            if use_guided_decoding:
                prompt = wrap_prompt_with_json_format(prompt, csv_date, use_guided_decoding=True)
            return prompt
        else:
            print(f"[WARN] No fast prompt for '{task_key}', falling back to standard prompt")

    if task_key not in _PROMPTS:
        raise KeyError(f"No prompt found for task '{task_key}'. Known: {list(_PROMPTS.keys())}")

    template = _PROMPTS[task_key]["template"]

    # Format fewshots (truncate long notes to avoid oversized prompts)
    fewshots_text = ""
    if fewshots:
        fewshots_parts = []
        for note, annotation in fewshots:
            truncated = note[:MAX_FEWSHOT_NOTE_CHARS] + "..." if len(note) > MAX_FEWSHOT_NOTE_CHARS else note
            fewshots_parts.append(
                f'Example:\n- Medical Note: {truncated}\n- Response: {{"final_output": "{annotation}"}}'
            )
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
        prompt = wrap_prompt_with_json_format(prompt, csv_date, use_guided_decoding=use_guided_decoding)

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

            _fewshot_builder = FewshotBuilder(store_dir=faiss_dir, use_gpu=False)

            # Try to preload existing indexes from disk
            _ensure_prompts_loaded()
            prompt_types = list(_PROMPTS.keys())
            _fewshot_builder.preload_all_indexes(prompt_types)

            # If no indexes loaded, build from fewshots.json data
            if not _fewshot_builder.indexes and _simple_fewshots:
                print("[INFO] No FAISS indexes found, building from fewshots.json...")
                built = _fewshot_builder.build_index_from_fewshots(_simple_fewshots)
                print(f"[INFO] Built {built} FAISS indexes from fewshots.json")
        except Exception as e:
            print(f"[ERROR] Failed to initialize FewshotBuilder: {e}")
            _fewshot_builder = None
            print(f"[WARN] Continuing in zero-shot mode (no few-shot examples)")
            return None

    return _fewshot_builder


_KNOWN_CENTER_SUFFIXES = ("-int-sarc", "-int-hnc", "-msci", "-vgr", "-int")

def _strip_center_suffix(key: str) -> str:
    """Strip known center suffix from a fewshot/prompt key to get the base name.
    E.g., 'ageatdiagnosis-int-sarc' → 'ageatdiagnosis',
          'ageatdiagnosis-int' → 'ageatdiagnosis'
    """
    for suffix in _KNOWN_CENTER_SUFFIXES:
        if key.endswith(suffix):
            return key[:-len(suffix)]
    return key


def _get_fewshot_examples(prompt_type: str, note_text: str, k: int = 5) -> List[Tuple[str, str]]:
    """
    Get few-shot examples using either FAISS builder or simple storage.
    Returns empty list if none available (zero-shot mode).
    """
    # Try FAISS builder first (if available) — semantic similarity search
    builder = _get_fewshot_builder()
    if builder is not None:
        try:
            # Try exact key first
            examples = builder.get_fewshot_examples(prompt_type, note_text, k=k)
            if examples:
                return examples
            # Legacy fallback: try base name match against FAISS indexes
            base = _strip_center_suffix(prompt_type)
            for idx_key in list(builder.indexes.keys()):
                if _strip_center_suffix(idx_key) == base:
                    examples = builder.get_fewshot_examples(idx_key, note_text, k=k)
                    if examples:
                        return examples
        except Exception as e:
            print(f"[WARN] FAISS few-shot retrieval failed: {e}, falling back to simple storage")

    # Exact match (new center-specific keys, e.g. "gender-int-sarc")
    if prompt_type in _simple_fewshots:
        return _simple_fewshots[prompt_type][:k]

    # Legacy fallback: match by base name for old "-int" suffixed keys
    # e.g., prompt_type="gender-int-sarc" → base="gender" → matches "gender-int"
    base = _strip_center_suffix(prompt_type)
    for fk in _simple_fewshots:
        if _strip_center_suffix(fk) == base:
            return _simple_fewshots[fk][:k]

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


# Pre-compiled regex patterns used in prompt processing
_RE_UNUSED_TOKEN = re.compile(r'^<unused\d+>\w+\s*', re.IGNORECASE)
_RE_REASONING_PREFIX = re.compile(
    r'^(The user wants me to|I need to|They have provided).*?\.\s*',
    re.IGNORECASE | re.DOTALL
)
_RE_ANNOTATION_PREFIX = re.compile(r'^\s*annotation\s*:\s*', re.IGNORECASE)


async def _process_single_prompt(
    prompt_type: str,
    note_text: str,
    csv_date: Optional[str],
    vllm_client: Any,
    use_structured: bool,
    request_use_fewshots: bool,
    request_fewshot_k: int,
    evaluation_mode: str = "validation",
    session_data: Optional[Dict] = None,
    note_id: Optional[str] = None,
    fast_mode: bool = False,
    icdo3_llm_cache: Optional[Dict[str, Any]] = None,
) -> AnnotationResult:
    """
    Process a single prompt type for a note, with timing instrumentation.
    Process a single prompt type for a note. Called sequentially.
    """
    timer = TimingBreakdown()
    timer.start_total()

    try:
        # --- Fewshot retrieval ---
        with timer.measure("fewshot_retrieval"):
            if fast_mode:
                if request_use_fewshots:
                    fewshot_examples = _get_fewshot_examples(prompt_type, note_text, k=request_fewshot_k)
                else:
                    fewshot_examples = []
            elif request_use_fewshots:
                fewshot_examples = _get_fewshot_examples(
                    prompt_type, note_text, k=request_fewshot_k
                )
            else:
                fewshot_examples = []

            # --- Optional fewshot sanitization ---
            if fewshot_examples and vllm_client.config.get("sanitize_fewshots", False):
                fewshot_examples = _sanitize_fewshot_examples(fewshot_examples)

        # --- Determine guided decoding mode ---
        # Guided decoding is beneficial for both standard and fast mode:
        # - Standard: guarantees valid JSON, eliminates thinking block issues
        # - Fast: even more critical due to smaller token budget (256-512 tokens)
        _structured_output_cfg = vllm_client.config.get("structured_output", {})
        _use_guided_decoding = _structured_output_cfg.get("enabled", False)

        # --- Token budget & chunking ---
        fast_max_tokens = 256 if fast_mode else 512
        _chunker = NoteChunker.get_instance()
        _probe_prompt = _get_prompt(
            task_key=prompt_type,
            fewshots=fewshot_examples,
            note_text="",
            csv_date=csv_date,
            fast_mode=fast_mode,
            use_guided_decoding=_use_guided_decoding,
        )
        _available_tokens = _chunker.calculate_available_tokens(_probe_prompt, fast_max_tokens)
        _note_chunks = _chunker.chunk_note(note_text, _available_tokens)
        _needs_chunking = len(_note_chunks) > 1
        if _needs_chunking:
            import logging as _log
            _log.getLogger(__name__).warning(
                f"[NoteChunker] Note {note_id!r} exceeds token budget "
                f"({_chunker.count_tokens(note_text)} tokens > {_available_tokens} available). "
                f"Splitting into {len(_note_chunks)} chunks."
            )

        _last_result: Optional[AnnotationResult] = None
        _is_repeatable = _is_repeatable_entity(prompt_type)
        _all_chunk_results: List[AnnotationResult] = []  # For repeatable entities: collect all confident chunks
        for _chunk_idx, _chunk_text in enumerate(_note_chunks):
            # --- Prompt building ---
            with timer.measure("prompt_building"):
                prompt = _get_prompt(
                    task_key=prompt_type,
                    fewshots=fewshot_examples,
                    note_text=_chunk_text,
                    csv_date=csv_date,
                    fast_mode=fast_mode,
                    use_guided_decoding=_use_guided_decoding,
                )
                raw_prompt = prompt
                template = _PROMPTS[prompt_type]["template"]
                is_simple = _is_simple_prompt(template)

        # --- vLLM inference (dominant cost) ---
        # Token budgets: generous enough to accommodate thinking-model preamble
        # (MedGemma emits <unused94>thought</unused94> blocks before the JSON answer;
        # too-small budgets exhaust mid-thought leaving nothing to parse).
        raw_response = None
        fast_max_tokens = (
            vllm_client.config.get("max_new_tokens_fast", 512) if fast_mode
            else vllm_client.config.get("max_new_tokens_standard", 2048)
        )
        # Extra kwargs for fast mode: try to suppress thinking tokens at the API level.
        # vLLM forwards unknown extra_body keys to the backend; if the model/server
        # doesn't support it the parameter is silently ignored.
        _fast_extra: dict = {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}} if fast_mode else {}

        # Prepare guided decoding response_format if applicable
        # Uses per-prompt constrained schema when possible (enum on final_output),
        # otherwise falls back to generic schema (fast or standard).
        _guided_response_format = None
        if _use_guided_decoding and not is_simple:
            from services.structured_generator import get_prompt_schema
            _prompt_entity_mapping_for_schema = (
                _PROMPTS.get(prompt_type, {}).get("entity_mapping")
                or _FAST_PROMPTS.get(prompt_type, {}).get("entity_mapping")
                or {}
            )
            _guided_response_format = get_prompt_schema(
                prompt_type=prompt_type,
                entity_mapping=_prompt_entity_mapping_for_schema,
                fast_mode=fast_mode,
            )

        _actual_guided = False  # Track whether guided decoding was actually used
        with timer.measure("vllm_inference"):
            async with _vllm_semaphore:
                if is_simple:
                    output = await vllm_client.agenerate(
                        prompt=prompt, max_new_tokens=fast_max_tokens,
                        temperature=0.0, return_logprobs=False, **_fast_extra
                    )
                    raw_output = output.get("raw", output.get("normalized", ""))
                    raw_response = raw_output
                else:
                    # Use guided decoding if enabled, with fallback on failure
                    if _use_guided_decoding and not is_simple:
                        try:
                            output = await vllm_client.agenerate(
                                prompt=prompt, max_new_tokens=fast_max_tokens,
                                temperature=0.0, return_logprobs=False,
                                response_format=_guided_response_format,
                            )
                            raw_output = output.get("raw", output.get("normalized", ""))
                            raw_response = raw_output
                            _actual_guided = True
                        except Exception as e:
                            import logging as _log
                            _log.getLogger(__name__).warning(
                                "Guided decoding failed (server may not support response_format), "
                                "falling back to unstructured generation: %s", e
                            )
                            _actual_guided = False

                    if not _actual_guided:
                        output = await vllm_client.agenerate(
                            prompt=prompt, max_new_tokens=fast_max_tokens,
                            temperature=0.0, return_logprobs=False, **_fast_extra
                        )
                        raw_output = output.get("raw", output.get("normalized", ""))
                        raw_response = raw_output

            # --- Post-processing ---
            with timer.measure("post_processing"):
                from lib.annotation_normalizer import normalize_annotation_output
                from models.annotation_models import StructuredAnnotation as SA
                from services.structured_generator import parse_structured_annotation

                if is_simple:
                    cleaned_output = raw_output.strip()
                    cleaned_output = _RE_UNUSED_TOKEN.sub('', cleaned_output)
                    cleaned_output = _RE_REASONING_PREFIX.sub('', cleaned_output)
                    cleaned_output = cleaned_output.strip()
                    if not cleaned_output or len(cleaned_output) < 5:
                        cleaned_output = raw_output.strip()
                    structured_ann = SA(
                        evidence="",
                        reasoning="Simple completion prompt - no structured parsing applied",
                        final_output=cleaned_output,
                        is_negated=False,
                        date=None
                    )
                else:
                    # Parse output using layered strategy (direct JSON → extraction → regex)
                    structured_ann = parse_structured_annotation(
                        raw_output=raw_output,
                        csv_date=csv_date,
                        used_guided_decoding=_actual_guided,
                        fast_mode=fast_mode,
                    )

                annotation_text = normalize_annotation_output(
                    structured_ann.final_output,
                    prompt_type=prompt_type,
                    normalize_absence=True
                )
                if not is_simple and not _actual_guided:
                    annotation_text = _RE_ANNOTATION_PREFIX.sub('', annotation_text).strip()

                # Re-wrap bare values (e.g., "deep" → "Tumor depth: deep.")
                from lib.annotation_normalizer import re_wrap_bare_value
                _raw_template = ""
                if fast_mode and prompt_type in _FAST_PROMPTS:
                    _raw_template = _FAST_PROMPTS[prompt_type].get("template", "")
                elif prompt_type in _PROMPTS:
                    _raw_template = _PROMPTS[prompt_type].get("template", "")
                if _raw_template:
                    annotation_text = re_wrap_bare_value(annotation_text, _raw_template)

                reasoning = structured_ann.reasoning
                evidence = ""  # Evidence field removed from LLM output; derive spans from reasoning
                is_negated = structured_ann.is_negated
                date_info = structured_ann.date

                # Derive evidence spans from reasoning text (references note phrases)
                evidence_spans = _extract_evidence_spans(_chunk_text, reasoning, prompt_type)
                values = _parse_annotation_values(annotation_text, _chunk_text, prompt_type)

            # --- ICD-O-3 extraction (async, non-blocking) ---
            icdo3_code_info = None
            with timer.measure("icdo3_extraction"):
                try:
                    from lib.icdo3_extractor import extract_icdo3_from_text_async, is_histology_or_site_prompt, _is_histology_prompt
                    if is_histology_or_site_prompt(prompt_type):
                        icdo3_code_info = await extract_icdo3_from_text_async(
                            annotation_text, prompt_type,
                            note_text=_chunk_text, vllm_client=vllm_client,
                            icdo3_llm_cache=icdo3_llm_cache,
                        )
                        if icdo3_code_info:
                            from models.schemas import ICDO3CodeInfo
                            if isinstance(icdo3_code_info, dict):
                                icdo3_code_info = ICDO3CodeInfo(**icdo3_code_info)

                            # For histology prompts, replace any topography code (Cxx.x)
                            # in the annotation text with the correct morphology code
                            if _is_histology_prompt(prompt_type):
                                morph_code = None
                                if isinstance(icdo3_code_info, ICDO3CodeInfo):
                                    morph_code = icdo3_code_info.morphology_code
                                elif isinstance(icdo3_code_info, dict):
                                    morph_code = icdo3_code_info.get('morphology_code')
                                if morph_code:
                                    import re as _re
                                    new_text = annotation_text
                                    # Replace topography codes (Cxx.x) in parentheses
                                    new_text = _re.sub(
                                        r'\(C\d{2}\.\d\)',
                                        f'({morph_code})',
                                        new_text,
                                    )
                                    # Replace placeholder patterns (may survive if validator didn't strip)
                                    new_text = _re.sub(
                                        r'\(\[select ICD-O-3 code\]\)',
                                        f'({morph_code})',
                                        new_text,
                                        flags=_re.IGNORECASE,
                                    )
                                    # If no code was replaced and annotation doesn't already
                                    # contain a morphology code, append it before trailing period.
                                    # This handles the case where the Pydantic validator already
                                    # stripped the placeholder text.
                                    if new_text == annotation_text and morph_code not in annotation_text:
                                        if new_text.endswith('.'):
                                            new_text = new_text[:-1].rstrip() + f' ({morph_code}).'
                                        else:
                                            new_text = new_text.rstrip() + f' ({morph_code})'
                                    if new_text != annotation_text:
                                        print(f"[INFO] Replaced/appended code in annotation: {annotation_text} → {new_text}")
                                        annotation_text = new_text
                                        # Re-parse values with updated text
                                        values = _parse_annotation_values(annotation_text, _chunk_text, prompt_type)
                except Exception as e:
                    print(f"[ERROR] Failed to extract ICD-O-3 code for {prompt_type}: {e}")

            # --- Evaluation ---
            evaluation_result = None
            with timer.measure("evaluation"):
                if evaluation_mode == "evaluation" and EVALUATION_SERVICE_AVAILABLE and session_data and note_id:
                    try:
                        expected_annotation = None
                        for note in session_data.get("notes", []):
                            if note.get("note_id") == note_id:
                                annotations_str = note.get("annotations")
                                if annotations_str:
                                    parts = str(annotations_str).split('|')
                                    for part in parts:
                                        part = part.strip()
                                        if ':' in part:
                                            key_part, value_part = part.split(':', 1)
                                            key_part = key_part.strip()
                                            if prompt_type.lower() in key_part.lower() or key_part.lower() in prompt_type.lower():
                                                expected_annotation = value_part.strip()
                                                break
                                    if not expected_annotation:
                                        pattern = re.compile(rf'{re.escape(prompt_type)}\s*:\s*([^|]+)', re.IGNORECASE | re.DOTALL)
                                        match = pattern.search(str(annotations_str))
                                        if match:
                                            expected_annotation = match.group(1).strip()
                                break

                        tmpl = None
                        if prompt_type in _PROMPTS:
                            prompt_info = _PROMPTS[prompt_type]
                            tmpl = prompt_info.get("template", "") if isinstance(prompt_info, dict) else prompt_info

                        if tmpl and evaluate_annotation_with_template:
                            evaluation_result = evaluate_annotation_with_template(
                                expected=expected_annotation or "",
                                predicted=annotation_text,
                                template=tmpl,
                                note_id=note_id,
                                prompt_type=prompt_type
                            )
                        elif evaluate_annotation_with_special_cases:
                            evaluation_result = evaluate_annotation_with_special_cases(
                                expected=expected_annotation or "",
                                predicted=annotation_text,
                                note_id=note_id,
                                prompt_type=prompt_type
                            )
                    except Exception as e:
                        print(f"[ERROR] Failed to evaluate annotation: {e}")

            # --- Build result ---
            # Convert date_info
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
            if not date_info_dict and csv_date:
                date_info_dict = {
                    "date_value": csv_date,
                    "source": "derived_from_csv",
                    "csv_date": csv_date
                }

            # Convert ICD-O-3 code
            icdo3_code_dict = None
            if icdo3_code_info:
                if hasattr(icdo3_code_info, 'dict'):
                    icdo3_code_dict = icdo3_code_info.dict()
                elif isinstance(icdo3_code_info, dict):
                    icdo3_code_dict = icdo3_code_info

            # Determine status
            status = "success"
            if annotation_text.startswith("ERROR:"):
                status = "error"
            elif reasoning and reasoning.endswith("...") and len(reasoning) >= 1997:
                # Only flag as incomplete when reasoning hit the 2000-char
                # truncation limit (Pydantic validator), indicating the LLM
                # may have run out of tokens.  Long reasoning is expected.
                status = "incomplete"
            elif not annotation_text or annotation_text.strip() == "":
                if reasoning:
                    reasoning_lower = reasoning.lower()
                    no_info_indicators = [
                        "not available", "not mentioned", "not stated", "not provided",
                        "unknown", "cannot be determined", "cannot be determined from",
                        "does not state", "does not provide", "does not mention",
                        "information is not available", "no information", "not found"
                    ]
                    if any(indicator in reasoning_lower for indicator in no_info_indicators):
                        status = "success"
                    else:
                        status = "error"
                else:
                    status = "error"

            # Resolve output_word_mappings against the raw LLM output
            from lib.output_mapper import resolve_output_word_mappings as _resolve_owm
            _prompt_entity_mapping = (
                _PROMPTS.get(prompt_type, {}).get("entity_mapping")
                or _FAST_PROMPTS.get(prompt_type, {}).get("entity_mapping")
                or {}
            )
            _derived_field_values = _resolve_owm(structured_ann.final_output, _prompt_entity_mapping) or None

            # --- Hallucination detection (repetition/looping) ---
            # Extract full reasoning from raw JSON before Pydantic truncates it.
            # The raw output may be truncated (LLM ran out of tokens) so json.loads() can fail;
            # in that case fall back to regex extraction and also scan the raw output directly.
            from services.structured_generator import detect_repetition_hallucination
            _raw_reasoning_full = reasoning or ""
            _raw_output_for_hal = ""
            if raw_output:
                try:
                    import json as _json_hal
                    _parsed_raw = _json_hal.loads(raw_output)
                    if isinstance(_parsed_raw, dict):
                        _raw_reasoning_full = _parsed_raw.get("reasoning", _raw_reasoning_full)
                except (ValueError, TypeError):
                    # Truncated JSON — try regex extraction of reasoning field
                    import re as _re_hal
                    _m = _re_hal.search(r'"reasoning"\s*:\s*"(.*?)(?:"\s*,|\Z)', raw_output, _re_hal.DOTALL)
                    if _m and len(_m.group(1)) > len(_raw_reasoning_full):
                        _raw_reasoning_full = _m.group(1)
                    # Also pass raw output for direct scanning
                    _raw_output_for_hal = raw_output
            _hallucination_flags = detect_repetition_hallucination(
                reasoning=_raw_reasoning_full,
                raw_output=_raw_output_for_hal,
            )

            _last_result = AnnotationResult(
                prompt_type=prompt_type,
                annotation_text=annotation_text,
                values=values,
                confidence_score=None,
                evidence_spans=evidence_spans,
                reasoning=reasoning,
                is_negated=is_negated,
                date_info=date_info_dict,
                evidence_text=evidence,
                raw_prompt=raw_prompt,
                raw_response=raw_response if raw_response is not None else "No response generated",
                status=status,
                evaluation_result=evaluation_result,
                icdo3_code=icdo3_code_dict,
                timing_breakdown=timer.to_dict(),
                derived_field_values=_derived_field_values,
                hallucination_flags=_hallucination_flags,
            )

            # --- Early stop for chunked notes ---
            if not _needs_chunking:
                return _last_result  # Normal path: no chunk_info attached

            # Extract raw final_output from JSON response for reliable confidence check.
            # (fallback parser may return the full JSON string as final_output)
            _value_for_confidence = annotation_text
            if raw_response:
                try:
                    import json as _json
                    _parsed_resp = _json.loads(raw_response)
                    if isinstance(_parsed_resp, dict) and "final_output" in _parsed_resp:
                        _value_for_confidence = str(_parsed_resp["final_output"])
                except Exception:
                    pass
            _is_confident = NoteChunker.is_confident_result(_value_for_confidence)
            _is_last_chunk = (_chunk_idx == len(_note_chunks) - 1)

            if _is_repeatable and _needs_chunking:
                # For repeatable entities: collect ALL confident chunk results, don't early-exit
                if _is_confident:
                    _last_result.chunk_info = ChunkInfo(
                        was_chunked=True,
                        total_chunks=len(_note_chunks),
                        answer_chunk_index=_chunk_idx + 1,
                        chunks_exhausted=False,
                    )
                    _all_chunk_results.append(_last_result)
                if _is_last_chunk:
                    if _all_chunk_results:
                        # Aggregate all chunk results into one with multiple values
                        return aggregate_multi_value_results(
                            results=_all_chunk_results,
                            prompt_type=prompt_type,
                            total_events=len(_note_chunks),
                        )
                    else:
                        # No confident results from any chunk
                        _last_result.chunk_info = ChunkInfo(
                            was_chunked=True,
                            total_chunks=len(_note_chunks),
                            answer_chunk_index=_chunk_idx + 1,
                            chunks_exhausted=True,
                        )
                        return _last_result
            else:
                # Non-repeatable entity: existing early-exit behavior
                if _is_confident or _is_last_chunk:
                    _last_result.chunk_info = ChunkInfo(
                        was_chunked=True,
                        total_chunks=len(_note_chunks),
                        answer_chunk_index=_chunk_idx + 1,
                        chunks_exhausted=not _is_confident,
                    )
                    return _last_result

        # Fallback (should not be reached for non-empty chunk lists)
        return _last_result

    except Exception as e:
        print(f"[ERROR] Failed to process {prompt_type}: {e}")
        import traceback
        traceback.print_exc()
        return AnnotationResult(
            prompt_type=prompt_type,
            annotation_text=f"ERROR: {str(e)}",
            values=[],
            evidence_spans=[],
            reasoning=None,
            is_negated=None,
            date_info=None,
            evidence_text=None,
            raw_prompt=prompt if 'prompt' in locals() else "Prompt not available",
            raw_response=raw_response if 'raw_response' in locals() and raw_response else f"Error occurred: {str(e)}",
            status="error",
            timing_breakdown=timer.to_dict(),
        )


async def _process_prompt_with_splitting(
    prompt_type: str,
    note_text: str,
    note_split_result: Optional[NoteSplitResult],
    csv_date: Optional[str],
    vllm_client: Any,
    use_structured: bool,
    request_use_fewshots: bool,
    request_fewshot_k: int,
    evaluation_mode: str = "validation",
    session_data: Optional[Dict] = None,
    note_id: Optional[str] = None,
    fast_mode: bool = False,
    icdo3_llm_cache: Optional[Dict[str, Any]] = None,
) -> AnnotationResult:
    """Process a prompt type, using split sub-notes for repeatable entities on history notes.

    For repeatable entity types (cardinality 0) on history notes, processes each
    sub-note independently and aggregates results. For non-repeatable types or
    non-history notes, delegates directly to _process_single_prompt.
    """
    # If note was split AND this prompt is for a repeatable entity, process each sub-note
    if (
        note_split_result is not None
        and note_split_result.was_split
        and _is_repeatable_entity(prompt_type)
    ):
        sub_results: List[AnnotationResult] = []
        for event in note_split_result.events:
            sub_note = build_sub_note(note_split_result.shared_context, event)
            result = await _process_single_prompt(
                prompt_type=prompt_type,
                note_text=sub_note,
                csv_date=csv_date,
                vllm_client=vllm_client,
                use_structured=use_structured,
                request_use_fewshots=request_use_fewshots,
                request_fewshot_k=request_fewshot_k,
                evaluation_mode=evaluation_mode,
                session_data=session_data,
                note_id=note_id,
                fast_mode=fast_mode,
                icdo3_llm_cache=icdo3_llm_cache,
            )
            sub_results.append(result)

        return aggregate_multi_value_results(
            results=sub_results,
            prompt_type=prompt_type,
            total_events=len(note_split_result.events),
        )

    # Non-repeatable entity or non-history note: use existing single-prompt processing
    return await _process_single_prompt(
        prompt_type=prompt_type,
        note_text=note_text,
        csv_date=csv_date,
        vllm_client=vllm_client,
        use_structured=use_structured,
        request_use_fewshots=request_use_fewshots,
        request_fewshot_k=request_fewshot_k,
        evaluation_mode=evaluation_mode,
        session_data=session_data,
        note_id=note_id,
        fast_mode=fast_mode,
        icdo3_llm_cache=icdo3_llm_cache,
    )


@router.post("/process", response_model=ProcessNoteResponse)
async def process_note(request: ProcessNoteRequest, session_id: str, note_text: str):
    """Process a single note with selected prompts using parallel structured generation"""
    _ensure_prompts_loaded()
    total_timer = TimingBreakdown()
    total_timer.start_total()

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
            for note in session_data.get("notes", []):
                if note.get("note_id") == request.note_id:
                    csv_date = note.get("date")
                    report_type = note.get("report_type")
                    break
    except Exception as e:
        print(f"[WARN] Could not load session: {e}")

    # Filter prompt types based on report_type_mapping + note_prompt_overrides - note_prompt_exclusions
    note_overrides = session_data.get("note_prompt_overrides", {}) if session_data else {}
    note_exclusions = session_data.get("note_prompt_exclusions", {}) if session_data else {}
    prompt_types_to_process = _get_applicable_prompts(
        note_id=request.note_id,
        requested_prompt_types=request.prompt_types,
        report_type=report_type,
        report_type_mapping=report_type_mapping,
        note_prompt_overrides=note_overrides,
        note_prompt_exclusions=note_exclusions,
    )

    # Check structured generation availability
    try:
        from services.structured_generator import OUTLINES_AVAILABLE
        use_structured = OUTLINES_AVAILABLE
    except ImportError:
        use_structured = False

    # --- History note detection & splitting ---
    note_split_result: Optional[NoteSplitResult] = None
    _splitting_config = vllm_client.config.get("history_splitting", {})
    _splitting_enabled = _splitting_config.get("enabled", True)
    if _splitting_enabled:
        _det_thresholds = _splitting_config.get("detection_thresholds", {})
        history_detector = get_history_detector(
            min_date_count=_det_thresholds.get("min_date_count", 3),
            min_event_markers=_det_thresholds.get("min_event_markers", 3),
            min_distinct_treatment_types=_det_thresholds.get("min_distinct_treatment_types", 2),
        )
        _detection = history_detector.get_detection_details(note_text, report_type or "")
    else:
        _detection = {"is_history": False}
    if _detection["is_history"]:
        print(
            f"[INFO] History note detected for {request.note_id} "
            f"(confidence={_detection['confidence']:.2f}, "
            f"events_est={_detection['detected_events_estimate']}, "
            f"methods={_detection['detection_methods']})"
        )
        # Check if we have any repeatable entity prompts that would benefit from splitting
        _has_repeatable = any(_is_repeatable_entity(pt) for pt in prompt_types_to_process)
        if _has_repeatable:
            note_split_result = await split_history_note(
                note_text=note_text,
                vllm_client=vllm_client,
                session_id=session_id,
                note_id=request.note_id,
            )
            if note_split_result.was_split:
                print(
                    f"[INFO] Split note {request.note_id} into "
                    f"{len(note_split_result.events)} events: "
                    f"{[e.event_type for e in note_split_result.events]}"
                )

    # Process all prompt types in parallel (semaphore limits concurrent GPU access)
    mode_label = "FAST" if request.fast_mode else "standard"
    print(f"[INFO] Processing {len(prompt_types_to_process)} prompts in parallel, mode={mode_label}")
    icdo3_llm_cache: Dict[str, Any] = {}
    note_annotations = list(await asyncio.gather(*[
        _process_prompt_with_splitting(
            prompt_type=pt,
            note_text=note_text,
            note_split_result=note_split_result,
            csv_date=csv_date,
            vllm_client=vllm_client,
            use_structured=use_structured,
            request_use_fewshots=request.use_fewshots,
            request_fewshot_k=request.fewshot_k,
            evaluation_mode=evaluation_mode,
            session_data=session_data,
            note_id=request.note_id,
            fast_mode=request.fast_mode,
            icdo3_llm_cache=icdo3_llm_cache,
        )
        for pt in prompt_types_to_process
    ]))

    processing_time = total_timer.get_total()
    # Aggregate timing: sum per-step times across all prompts
    agg_timing: Dict[str, float] = {}
    for ann in note_annotations:
        if ann.timing_breakdown:
            for step, dur in ann.timing_breakdown.items():
                agg_timing[step] = agg_timing.get(step, 0.0) + dur
    agg_timing["wall_clock_total"] = processing_time
    agg_timing["prompt_count"] = float(len(prompt_types_to_process))

    _history_detection_payload = None
    if _detection["is_history"]:
        _history_detection_payload = {
            "is_history": True,
            "was_split": note_split_result is not None and note_split_result.was_split,
            "events_count": len(note_split_result.events) if note_split_result and note_split_result.was_split else 0,
            "detection_methods": _detection.get("detection_methods", []),
            "date_count": _detection.get("date_count", 0),
            "event_marker_count": _detection.get("event_marker_count", 0),
            "treatment_types_found": _detection.get("treatment_types_found", []),
            "events": [
                {"event_text": e.event_text, "event_type": e.event_type, "event_date": e.event_date}
                for e in note_split_result.events
            ] if note_split_result and note_split_result.was_split else [],
        }

    return ProcessNoteResponse(
        note_id=request.note_id,
        note_text=note_text,
        annotations=note_annotations,
        processing_time_seconds=processing_time,
        timing_breakdown=agg_timing,
        history_detection=_history_detection_payload,
    )


async def _tagged_process(
    note_id: str,
    prompt_type: str,
    **kwargs,
) -> Tuple[str, str, AnnotationResult]:
    """Wrapper around _process_single_prompt that returns (note_id, prompt_type, result)."""
    result = await _process_single_prompt(prompt_type=prompt_type, note_id=note_id, **kwargs)
    return (note_id, prompt_type, result)


@router.post("/batch", response_model=BatchProcessResponse)
async def batch_process(request: BatchProcessRequest, session_id: str = Query(...)):
    """Batch process multiple notes with parallel vLLM calls"""
    _ensure_prompts_loaded()
    batch_timer = TimingBreakdown()
    batch_timer.start_total()

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

    evaluation_mode = session.get('evaluation_mode', 'validation')

    # Get vLLM client
    vllm_client = get_vllm_client()
    if not vllm_client.is_available():
        status = vllm_client.get_status()
        error_detail = status.get("error", "Unknown error")
        endpoint = vllm_client.config.get("vllm_endpoint", "not configured")
        raise HTTPException(
            status_code=503,
            detail=f"VLLM server not available. Endpoint: {endpoint}, Error: {error_detail}. "
                   f"Please ensure the VLLM server is running and restart the backend if you moved the project directory."
        )

    note_dates = {}
    report_type_mapping = session.get('report_type_mapping')
    note_prompt_overrides = session.get('note_prompt_overrides', {})
    note_prompt_exclusions = session.get('note_prompt_exclusions', {})
    for note in session.get('notes', []):
        note_dates[note.get('note_id')] = note.get('date')

    try:
        from services.structured_generator import OUTLINES_AVAILABLE
        use_structured = OUTLINES_AVAILABLE
    except ImportError:
        use_structured = False

    # Collect all (note, prompt_type) pairs for parallel execution
    all_tasks = []  # List of (note_id, note_text, prompt_type, csv_date)
    note_order = []  # Track which notes we're processing

    for note_id in request.note_ids:
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

        prompt_types_to_process = _get_applicable_prompts(
            note_id=note_id,
            requested_prompt_types=request.prompt_types,
            report_type=report_type,
            report_type_mapping=report_type_mapping,
            note_prompt_overrides=note_prompt_overrides,
            note_prompt_exclusions=note_prompt_exclusions,
        )

        note_order.append((note_id, note_text, prompt_types_to_process, report_type))
        for pt in prompt_types_to_process:
            all_tasks.append((note_id, note_text, pt, csv_date))

    total_prompts = len(all_tasks)
    mode_label = "FAST" if request.fast_mode else "standard"
    print(f"[INFO] Batch: {len(note_order)} notes, {total_prompts} total prompts, parallel mode={mode_label}")

    # --- Pre-split history notes (one LLM call per history note, shared across prompts) ---
    _history_detector = get_history_detector()
    _note_splits: Dict[str, Optional[NoteSplitResult]] = {}
    _split_tasks = []
    for nid, ntxt, pts, rtype in note_order:
        detection = _history_detector.get_detection_details(ntxt, rtype or "")
        if detection["is_history"] and any(_is_repeatable_entity(pt) for pt in pts):
            _split_tasks.append((nid, ntxt))
        else:
            _note_splits[nid] = None

    if _split_tasks:
        print(f"[INFO] Splitting {len(_split_tasks)} history notes before batch processing")
        split_results = await asyncio.gather(*[
            split_history_note(
                note_text=ntxt,
                vllm_client=vllm_client,
                session_id=session_id,
                note_id=nid,
            )
            for nid, ntxt in _split_tasks
        ])
        for (nid, _), result in zip(_split_tasks, split_results):
            _note_splits[nid] = result if result.was_split else None

    # Process all notes in parallel. The _vllm_semaphore inside _process_single_prompt
    # limits concurrent GPU access (default VLLM_CONCURRENCY=2), so launching all tasks
    # is safe — they queue on the semaphore while overlapping CPU-bound work.
    async def _process_note(note_id: str, note_text: str, prompt_types_to_process: List[str], _report_type: Optional[str] = None) -> ProcessNoteResponse:
        icdo3_llm_cache: Dict[str, Any] = {}
        _split = _note_splits.get(note_id)
        note_annotations = await asyncio.gather(*[
            _process_prompt_with_splitting(
                prompt_type=pt,
                note_text=note_text,
                note_split_result=_split,
                csv_date=note_dates.get(note_id),
                vllm_client=vllm_client,
                use_structured=use_structured,
                request_use_fewshots=request.use_fewshots,
                request_fewshot_k=request.fewshot_k,
                evaluation_mode=evaluation_mode,
                session_data=session,
                note_id=note_id,
                fast_mode=request.fast_mode,
                icdo3_llm_cache=icdo3_llm_cache,
            )
            for pt in prompt_types_to_process
        ])

        note_timing: Dict[str, float] = {}
        for ann in note_annotations:
            if ann.timing_breakdown:
                for step, dur in ann.timing_breakdown.items():
                    note_timing[step] = note_timing.get(step, 0.0) + dur

        note_time = sum(
            (ann.timing_breakdown.get("total", 0.0) for ann in note_annotations if ann.timing_breakdown),
            0.0
        )

        return ProcessNoteResponse(
            note_id=note_id,
            note_text=note_text,
            annotations=list(note_annotations),
            processing_time_seconds=note_time,
            timing_breakdown=note_timing,
        )

    results = list(await asyncio.gather(*[
        _process_note(nid, ntxt, pts, rtype)
        for nid, ntxt, pts, rtype in note_order
    ]))

    batch_time = batch_timer.get_total()

    # Aggregate per-step timing across all notes and annotations
    agg_steps: Dict[str, float] = {}
    prompt_type_times: Dict[str, List[float]] = {}
    for note_result in results:
        for ann in note_result.annotations:
            if ann.timing_breakdown:
                for step, dur in ann.timing_breakdown.items():
                    agg_steps[step] = agg_steps.get(step, 0.0) + dur
            # Track per-prompt-type total time
            pt = ann.prompt_type or "unknown"
            total_for_ann = ann.timing_breakdown.get("total", 0.0) if ann.timing_breakdown else 0.0
            prompt_type_times.setdefault(pt, []).append(total_for_ann)

    batch_timing = {
        "wall_clock_total": batch_time,
        "note_count": float(len(note_order)),
        "prompt_count": float(total_prompts),
    }
    # Add aggregated step totals
    for step, total_dur in agg_steps.items():
        batch_timing[f"sum_{step}"] = total_dur
    # Add per-prompt-type averages
    for pt, times in prompt_type_times.items():
        if times:
            batch_timing[f"avg_{pt}"] = sum(times) / len(times)

    return BatchProcessResponse(
        results=results,
        total_time_seconds=batch_time,
        timing_breakdown=batch_timing,
    )


@router.post("/batch/stream")
async def batch_process_stream(request: BatchProcessRequest, session_id: str = Query(...)):
    """Batch process with SSE streaming. Sends progress events as each prompt
    completes, preventing reverse-proxy idle timeouts."""
    from sse_starlette.sse import EventSourceResponse
    import json as _json

    _ensure_prompts_loaded()
    batch_timer = TimingBreakdown()
    batch_timer.start_total()

    # --- same setup as batch_process ---
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

    evaluation_mode = session.get('evaluation_mode', 'validation')

    vllm_client = get_vllm_client()
    if not vllm_client.is_available():
        status = vllm_client.get_status()
        error_detail = status.get("error", "Unknown error")
        endpoint = vllm_client.config.get("vllm_endpoint", "not configured")
        raise HTTPException(
            status_code=503,
            detail=f"VLLM server not available. Endpoint: {endpoint}, Error: {error_detail}. "
                   f"Please ensure the VLLM server is running and restart the backend if you moved the project directory."
        )

    note_dates: Dict[str, Optional[str]] = {}
    report_type_mapping = session.get('report_type_mapping')
    note_prompt_overrides = session.get('note_prompt_overrides', {})
    note_prompt_exclusions = session.get('note_prompt_exclusions', {})
    for note in session.get('notes', []):
        note_dates[note.get('note_id')] = note.get('date')

    try:
        from services.structured_generator import OUTLINES_AVAILABLE
        use_structured = OUTLINES_AVAILABLE
    except ImportError:
        use_structured = False

    # Build task list (same logic as batch_process)
    all_tasks: List[Tuple[str, str, str, Optional[str]]] = []
    note_order: List[Tuple[str, str, List[str]]] = []

    for note_id in request.note_ids:
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

        prompt_types_to_process = _get_applicable_prompts(
            note_id=note_id,
            requested_prompt_types=request.prompt_types,
            report_type=report_type,
            report_type_mapping=report_type_mapping,
            note_prompt_overrides=note_prompt_overrides,
            note_prompt_exclusions=note_prompt_exclusions,
        )

        note_order.append((note_id, note_text, prompt_types_to_process, report_type))
        for pt in prompt_types_to_process:
            all_tasks.append((note_id, note_text, pt, csv_date))

    total_prompts = len(all_tasks)
    mode_label = "FAST" if request.fast_mode else "standard"
    print(f"[INFO] Batch-stream: {len(note_order)} notes, {total_prompts} total prompts, sequential mode={mode_label}")

    async def _event_generator():
        # Send initial event immediately (keeps proxy connection alive)
        yield {
            "event": "started",
            "data": _json.dumps({
                "total_notes": len(note_order),
                "total_prompts": total_prompts,
            }),
        }

        # Process notes and prompts sequentially, yielding progress after each
        results_by_note: Dict[str, List[AnnotationResult]] = {}
        completed = 0

        for nid, nt, prompt_types_to_process, _rtype in note_order:
            csv_date = note_dates.get(nid)
            icdo3_llm_cache: Dict[str, Any] = {}  # shared across prompt types for this note

            # History detection & splitting for streaming mode
            _stream_split: Optional[NoteSplitResult] = None
            _stream_det = get_history_detector().get_detection_details(nt, _rtype or "")
            if _stream_det["is_history"] and any(_is_repeatable_entity(pt) for pt in prompt_types_to_process):
                _stream_split = await split_history_note(
                    note_text=nt, vllm_client=vllm_client,
                    session_id=session_id, note_id=nid,
                )
                if not _stream_split.was_split:
                    _stream_split = None

            # Build history_detection payload for this note (only when detected)
            _stream_history_detection = None
            if _stream_det["is_history"]:
                _stream_history_detection = {
                    "is_history": True,
                    "was_split": _stream_split is not None,
                    "events_count": len(_stream_split.events) if _stream_split else 0,
                    "detection_methods": _stream_det.get("detection_methods", []),
                    "date_count": _stream_det.get("date_count", 0),
                    "event_marker_count": _stream_det.get("event_marker_count", 0),
                    "treatment_types_found": _stream_det.get("treatment_types_found", []),
                    "events": [
                        {"event_text": e.event_text, "event_type": e.event_type, "event_date": e.event_date}
                        for e in _stream_split.events
                    ] if _stream_split else [],
                }

            _first_prompt_for_note = True
            for pt in prompt_types_to_process:
                result = await _process_prompt_with_splitting(
                    prompt_type=pt,
                    note_text=nt,
                    note_split_result=_stream_split,
                    csv_date=csv_date,
                    vllm_client=vllm_client,
                    use_structured=use_structured,
                    request_use_fewshots=request.use_fewshots,
                    request_fewshot_k=request.fewshot_k,
                    evaluation_mode=evaluation_mode,
                    session_data=session,
                    note_id=nid,
                    fast_mode=request.fast_mode,
                    icdo3_llm_cache=icdo3_llm_cache,
                )
                completed += 1
                results_by_note.setdefault(nid, []).append(result)

                progress_data = {
                    "completed": completed,
                    "total": total_prompts,
                    "note_id": nid,
                    "prompt_type": pt,
                    "percentage": round(completed / total_prompts * 100) if total_prompts else 100,
                }
                if _first_prompt_for_note and _stream_history_detection:
                    progress_data["history_detection"] = _stream_history_detection
                    _first_prompt_for_note = False

                yield {
                    "event": "progress",
                    "data": _json.dumps(progress_data),
                }

        # Assemble final response (same structure as BatchProcessResponse)
        results = []
        for nid, nt, prompt_types_to_process, _rtype in note_order:
            note_annotations = results_by_note.get(nid, [])

            note_timing: Dict[str, float] = {}
            for ann in note_annotations:
                if ann.timing_breakdown:
                    for step, dur in ann.timing_breakdown.items():
                        note_timing[step] = note_timing.get(step, 0.0) + dur

            note_time = sum(
                (ann.timing_breakdown.get("total", 0.0) for ann in note_annotations if ann.timing_breakdown),
                0.0,
            )

            results.append(ProcessNoteResponse(
                note_id=nid,
                note_text=nt,
                annotations=note_annotations,
                processing_time_seconds=note_time,
                timing_breakdown=note_timing,
            ))

        batch_time = batch_timer.get_total()
        batch_timing = {
            "wall_clock_total": batch_time,
            "note_count": float(len(note_order)),
            "prompt_count": float(total_prompts),
        }

        final = BatchProcessResponse(
            results=results,
            total_time_seconds=batch_time,
            timing_breakdown=batch_timing,
        )

        yield {
            "event": "complete",
            "data": final.model_dump_json(),
        }

    return EventSourceResponse(_event_generator())


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


# ---------------------------------------------------------------------------
# Sequential processing endpoints — resilient per-note processing with
# incremental save and optional resume via skip_annotated
# ---------------------------------------------------------------------------

async def _sequential_process_core(
    request: SequentialProcessRequest,
    session_id: str,
):
    """Shared logic for sequential endpoints. Yields (event_type, data_dict) tuples."""
    import importlib.util
    import json as _json

    _ensure_prompts_loaded()
    if request.fast_mode:
        _ensure_fast_prompts_loaded()

    # Load session
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

    # Check vLLM
    vllm_client = get_vllm_client()
    if not vllm_client.is_available():
        status = vllm_client.get_status()
        error_detail = status.get("error", "Unknown error")
        endpoint = vllm_client.config.get("vllm_endpoint", "not configured")
        raise HTTPException(
            status_code=503,
            detail=f"VLLM server not available. Endpoint: {endpoint}, Error: {error_detail}. "
                   f"Please ensure the VLLM server is running."
        )

    # Check structured generation
    try:
        from services.structured_generator import OUTLINES_AVAILABLE
        use_structured = OUTLINES_AVAILABLE
    except ImportError:
        use_structured = False

    evaluation_mode = session.get('evaluation_mode', 'validation')
    report_type_mapping = session.get('report_type_mapping')
    note_prompt_overrides = session.get('note_prompt_overrides', {})
    note_prompt_exclusions = session.get('note_prompt_exclusions', {})

    # Determine prompt types
    prompt_types = request.prompt_types or session.get('prompt_types', [])

    # Determine notes to process
    all_notes = session.get('notes', [])
    if request.note_ids:
        requested_ids = set(request.note_ids)
        notes = [n for n in all_notes if n.get('note_id') in requested_ids]
    else:
        notes = all_notes

    # Build processing plan: filter prompts per note and handle skip_annotated
    processing_plan = []  # List of (note_data, applicable_prompts)
    skipped_results = []

    for note in notes:
        note_id = note.get('note_id', '')
        report_type = note.get('report_type')
        applicable = _get_applicable_prompts(
            note_id=note_id,
            requested_prompt_types=prompt_types,
            report_type=report_type,
            report_type_mapping=report_type_mapping,
            note_prompt_overrides=note_prompt_overrides,
            note_prompt_exclusions=note_prompt_exclusions,
        )
        if not applicable:
            skipped_results.append(SequentialNoteResult(
                note_id=note_id, status="skipped", error_message="No applicable prompts"
            ))
            continue

        if request.skip_annotated:
            existing = session.get('annotations', {}).get(note_id, {})
            if all(pt in existing for pt in applicable):
                skipped_results.append(SequentialNoteResult(
                    note_id=note_id, status="skipped"
                ))
                continue

        processing_plan.append((note, applicable))

    total_to_process = len(processing_plan)
    total_notes = len(notes)

    # Yield started event
    yield ("started", {
        "session_id": session_id,
        "total_notes": total_notes,
        "notes_to_process": total_to_process,
        "skipped": len(skipped_results),
    })

    # Process notes sequentially
    results = list(skipped_results)
    processed_count = 0
    error_count = 0
    overall_start = time.time()

    for idx, (note_data, applicable_prompts) in enumerate(processing_plan):
        note_id = note_data.get('note_id', '')
        note_text = note_data.get('text', '')
        csv_date = note_data.get('date')
        note_start = time.time()

        try:
            note_annotations = {}
            icdo3_llm_cache: Dict[str, Any] = {}  # shared across prompt types for this note

            # --- History note detection & splitting for sequential mode ---
            _seq_split: Optional[NoteSplitResult] = None
            _seq_report_type = note_data.get('report_type', '')
            _seq_detection = get_history_detector().get_detection_details(note_text, _seq_report_type)
            if _seq_detection["is_history"] and any(_is_repeatable_entity(pt) for pt in applicable_prompts):
                _seq_split = await split_history_note(
                    note_text=note_text,
                    vllm_client=vllm_client,
                    session_id=session_id,
                    note_id=note_id,
                )
                if not _seq_split.was_split:
                    _seq_split = None

            for pt in applicable_prompts:
                result = await _process_prompt_with_splitting(
                    prompt_type=pt,
                    note_text=note_text,
                    note_split_result=_seq_split,
                    csv_date=csv_date,
                    vllm_client=vllm_client,
                    use_structured=use_structured,
                    request_use_fewshots=request.use_fewshots,
                    request_fewshot_k=request.fewshot_k,
                    evaluation_mode=evaluation_mode,
                    session_data=session,
                    note_id=note_id,
                    fast_mode=request.fast_mode,
                    icdo3_llm_cache=icdo3_llm_cache,
                )
                note_annotations[pt] = _annotation_result_to_dict(result, note_id, pt)

            # Save annotations to session immediately
            if note_id not in session.get('annotations', {}):
                session.setdefault('annotations', {})[note_id] = {}
            session['annotations'][note_id].update(note_annotations)
            sessions_module._save_session(session_id, session)

            note_time = time.time() - note_start
            processed_count += 1
            note_result = SequentialNoteResult(
                note_id=note_id,
                status="success",
                annotations_count=len(note_annotations),
                processing_time_seconds=round(note_time, 2),
            )
            results.append(note_result)

            _seq_progress_data = {
                "note_id": note_id,
                "status": "success",
                "annotations_count": len(note_annotations),
                "completed": idx + 1,
                "total": total_to_process,
                "percentage": round((idx + 1) / total_to_process * 100, 1) if total_to_process else 100,
                "processing_time_seconds": round(note_time, 2),
            }
            if _seq_detection["is_history"]:
                _seq_progress_data["history_detection"] = {
                    "is_history": True,
                    "was_split": _seq_split is not None,
                    "events_count": len(_seq_split.events) if _seq_split else 0,
                    "detection_methods": _seq_detection.get("detection_methods", []),
                    "date_count": _seq_detection.get("date_count", 0),
                    "event_marker_count": _seq_detection.get("event_marker_count", 0),
                    "treatment_types_found": _seq_detection.get("treatment_types_found", []),
                    "events": [
                        {"event_text": e.event_text, "event_type": e.event_type, "event_date": e.event_date}
                        for e in _seq_split.events
                    ] if _seq_split else [],
                }
            yield ("progress", _seq_progress_data)

        except Exception as e:
            note_time = time.time() - note_start
            error_count += 1
            error_msg = str(e)
            print(f"[ERROR] Sequential processing failed for note {note_id}: {error_msg}")
            import traceback
            traceback.print_exc()

            note_result = SequentialNoteResult(
                note_id=note_id,
                status="error",
                error_message=error_msg,
                processing_time_seconds=round(note_time, 2),
            )
            results.append(note_result)

            yield ("progress", {
                "note_id": note_id,
                "status": "error",
                "error_message": error_msg,
                "completed": idx + 1,
                "total": total_to_process,
                "percentage": round((idx + 1) / total_to_process * 100, 1) if total_to_process else 100,
                "processing_time_seconds": round(note_time, 2),
            })
            continue  # Next note

    total_time = time.time() - overall_start

    # Compute timing summary from per-note results
    note_times = [r.processing_time_seconds for r in results if r.status == "success" and r.processing_time_seconds > 0]
    timing_summary = None
    if note_times:
        timing_summary = {
            "total_processing_time": round(sum(note_times), 2),
            "avg_per_note": round(sum(note_times) / len(note_times), 2),
            "min_per_note": round(min(note_times), 2),
            "max_per_note": round(max(note_times), 2),
        }

    response = SequentialProcessResponse(
        session_id=session_id,
        total_notes=total_notes,
        processed=processed_count,
        skipped=len(skipped_results),
        errors=error_count,
        results=results,
        total_time_seconds=round(total_time, 2),
        timing_summary=timing_summary,
    )
    yield ("complete", response.model_dump())


@router.post("/sequential", response_model=SequentialProcessResponse)
async def sequential_process(request: SequentialProcessRequest, session_id: str = Query(...)):
    """Process notes sequentially with per-note error handling and incremental save.

    Unlike /batch, this endpoint:
    - Saves annotations to disk after each note (crash resilient)
    - Catches per-note errors and continues processing
    - Supports skip_annotated for resume capability
    - Defaults to all notes and session prompt_types if not specified
    """
    final_response = None
    async for event_type, data in _sequential_process_core(request, session_id):
        if event_type == "complete":
            final_response = data

    if final_response is None:
        raise HTTPException(status_code=500, detail="Sequential processing produced no result")

    return SequentialProcessResponse(**final_response)


@router.post("/sequential/stream")
async def sequential_process_stream(request: SequentialProcessRequest, session_id: str = Query(...)):
    """Streaming variant of /sequential. Sends SSE progress events after each note."""
    from sse_starlette.sse import EventSourceResponse
    import json as _json

    async def _event_generator():
        try:
            async for event_type, data in _sequential_process_core(request, session_id):
                yield {
                    "event": event_type,
                    "data": _json.dumps(data, default=str),
                }
        except HTTPException as exc:
            yield {
                "event": "error",
                "data": _json.dumps({"detail": exc.detail, "status_code": exc.status_code}),
            }
        except Exception as exc:
            yield {
                "event": "error",
                "data": _json.dumps({"detail": str(exc), "status_code": 500}),
            }

    return EventSourceResponse(_event_generator())

