"""
Structured generation service for clinical annotations.

Supports two modes:
1. Guided decoding via vLLM response_format (json_schema) — guarantees valid JSON
2. Fallback regex-based parsing for legacy vLLM versions or when guided decoding fails

The primary entry point is `parse_structured_annotation()` which tries direct
Pydantic parsing first, then falls back through increasingly permissive strategies.
"""
import json
import logging
import re
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

from models.annotation_models import StructuredAnnotation, FastStructuredAnnotation, AnnotationDateInfo, HallucinationFlag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schemas for vLLM guided decoding (response_format parameter)
# ---------------------------------------------------------------------------

# Standard mode: all fields (reasoning, final_output, is_negated, date)
ANNOTATION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "structured_annotation",
        "schema": StructuredAnnotation.model_json_schema(),
    }
}

# Fast mode: only final_output, is_negated, date (no reasoning)
FAST_ANNOTATION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "fast_structured_annotation",
        "schema": FastStructuredAnnotation.model_json_schema(),
    }
}

# ---------------------------------------------------------------------------
# Pre-compiled regex patterns for fallback JSON extraction
# ---------------------------------------------------------------------------
_RE_MARKDOWN_JSON = re.compile(r'```(?:json)?\s*\n?(.*?)\n?```', re.DOTALL)
_RE_JSON_OBJ = re.compile(r'\{.*?"reasoning".*?"final_output".*?\}', re.DOTALL)
_RE_JSON_ARRAY = re.compile(r'\[\s*\{.*?"reasoning".*?"final_output".*?\}.*?\]', re.DOTALL)
_RE_JSON_OBJ_SINGLE = re.compile(r'\{[^{}]*"reasoning"[^{}]*"final_output"[^{}]*\}', re.DOTALL)
# Also match legacy format with evidence field (backward compat with old outputs)
_RE_JSON_OBJ_LEGACY = re.compile(r'\{.*?"evidence".*?"final_output".*?\}', re.DOTALL)
_RE_FAST_JSON = re.compile(r'\{[^{}]*"final_output"\s*:[^{}]*\}', re.DOTALL)

# Strip model thinking blocks
_RE_THINKING_BLOCK = re.compile(r'<unused\d+>\w+.*?</unused\d+>\s*', re.DOTALL | re.IGNORECASE)
_RE_THINKING_BLOCK_MEDGEMMA = re.compile(r'<unused\d+>.*?<unused\d+>\s*', re.DOTALL | re.IGNORECASE)
_RE_THINKING_BLOCK_UNCLOSED = re.compile(r'<unused\d+>.*$', re.DOTALL | re.IGNORECASE)

# Fallback text extraction patterns
_RE_REASONING = re.compile(r'Reasoning:\s*(.+?)(?:\.|$|Final)', re.IGNORECASE | re.DOTALL)
_RE_REASONING_INF = re.compile(r'Inference:\s*(.+?)(?:\.|$)', re.IGNORECASE | re.DOTALL)
_RE_ANNOTATION = re.compile(r'Annotation:\s*(.+?)(?:\.|$)', re.IGNORECASE | re.DOTALL)
_RE_FINAL_OUTPUT = re.compile(r'Final output:\s*(.+?)(?:\.|$)', re.IGNORECASE | re.DOTALL)
_RE_DATE_SLASH = re.compile(r'\d{2}/\d{2}/\d{4}')
_RE_DATE_ISO = re.compile(r'\d{4}-\d{2}-\d{2}')
_RE_DATE_FLEX = re.compile(r'\d{1,2}/\d{1,2}/\d{4}')

# Patterns for mining answers from unclosed thinking blocks
_RE_THINK_FINAL_JSON = re.compile(r'\{[^{}]*"final_output"\s*:\s*"([^"]+)"[^{}]*\}', re.DOTALL)
_RE_THINK_SHOULD_OUTPUT = re.compile(
    r'(?:final_output should be|I should output|output should be|the output is|output:\s*)["\s]*([^\n"]{4,200})',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Repetition / looping hallucination detection
# ---------------------------------------------------------------------------

_RE_SENTENCE_SPLIT = re.compile(r'[.!?]\s+|\n')


def _detect_repetition(text: str, threshold: float = 0.5) -> Optional[Dict[str, Any]]:
    """Detect looping/repetition hallucination in a single text field.

    Returns a dict with detection info if repetition found, None otherwise.
    """
    if not text or len(text) < 50:
        return None

    sentences = [s.strip() for s in _RE_SENTENCE_SPLIT.split(text) if len(s.strip()) > 20]
    if len(sentences) < 3:
        return None

    unique = set(sentences)
    duplicate_ratio = 1.0 - (len(unique) / len(sentences))

    if duplicate_ratio >= threshold:
        return {
            "severity": "high" if duplicate_ratio > 0.8 else "medium",
            "duplicate_ratio": round(duplicate_ratio, 2),
            "total_sentences": len(sentences),
            "unique_sentences": len(unique),
        }
    return None


def detect_repetition_hallucination(
    reasoning: str = "",
    raw_output: str = "",
) -> Optional[list[HallucinationFlag]]:
    """Run repetition detection on reasoning and raw output.

    Returns a list of HallucinationFlag if any repetition found, None otherwise.
    """
    flags: list[HallucinationFlag] = []

    for field_name, text in [("reasoning", reasoning), ("raw_output", raw_output)]:
        result = _detect_repetition(text)
        if result:
            flags.append(HallucinationFlag(
                type="repetition_loop",
                field=field_name,
                severity=result["severity"],
                duplicate_ratio=result["duplicate_ratio"],
                message=f"Repetitive output detected: {result['unique_sentences']}/{result['total_sentences']} unique sentences",
            ))

    return flags if flags else None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _try_extract_from_thinking(thinking_text: str) -> Optional[str]:
    """
    Try to extract the intended annotation from inside an unclosed thinking block.
    Called as a last resort when the model ran out of tokens before producing JSON.
    """
    m = _RE_THINK_FINAL_JSON.search(thinking_text)
    if m:
        return m.group(1).strip()

    m = _RE_THINK_SHOULD_OUTPUT.search(thinking_text)
    if m:
        candidate = m.group(1).strip().strip('"').strip("'")
        if len(candidate) >= 4:
            return candidate

    return None


def _strip_thinking_blocks(raw_output: str) -> str:
    """Strip MedGemma/model thinking blocks from raw output."""
    # MedGemma format: <unused94>thinking<unused95>response
    cleaned = _RE_THINKING_BLOCK_MEDGEMMA.sub('', raw_output, count=1).strip()
    # XML-style: <unused94>thinking</unused94>
    cleaned = _RE_THINKING_BLOCK.sub('', cleaned).strip()
    return cleaned


def _apply_csv_date(annotation: StructuredAnnotation, csv_date: Optional[str]) -> None:
    """Apply CSV date to annotation if needed (mutates in place)."""
    if csv_date and annotation.date and annotation.date.source == "derived_from_csv":
        annotation.date.csv_date = csv_date
    if not annotation.date and csv_date:
        annotation.date = AnnotationDateInfo(
            date_value=csv_date,
            source="derived_from_csv",
            csv_date=csv_date,
        )


def _extract_json_string(text: str) -> Optional[str]:
    """Try to extract a JSON string from text using multiple strategies."""
    # 1. Markdown code blocks
    md_match = _RE_MARKDOWN_JSON.search(text)
    if md_match:
        candidate = md_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # 2. JSON array pattern
    array_match = _RE_JSON_ARRAY.search(text)
    if array_match:
        try:
            parsed = json.loads(array_match.group(0))
            if isinstance(parsed, list) and len(parsed) > 0:
                return json.dumps(parsed[0])
        except json.JSONDecodeError:
            pass

    # 3. Full JSON object with known fields
    for pattern in [_RE_JSON_OBJ, _RE_JSON_OBJ_SINGLE, _RE_JSON_OBJ_LEGACY]:
        match = pattern.search(text)
        if match:
            try:
                json.loads(match.group(0))
                return match.group(0)
            except json.JSONDecodeError:
                continue

    # 4. Fast mode: minimal {"final_output": "..."}
    match = _RE_FAST_JSON.search(text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict) and "final_output" in parsed:
                full = {
                    "reasoning": "Fast mode: no reasoning captured",
                    "final_output": parsed["final_output"],
                    "is_negated": False,
                    "date": None,
                }
                return json.dumps(full)
        except json.JSONDecodeError:
            pass

    return None


def _regex_fallback_parse(raw_output: str, csv_date: Optional[str] = None) -> StructuredAnnotation:
    """
    Last-resort regex extraction when no valid JSON can be found.
    Extracts individual fields from free-form text.
    """
    logger.debug(f"Regex fallback parsing, output length: {len(raw_output)}")

    # Extract reasoning
    reasoning = ""
    for compiled_re in [_RE_REASONING, _RE_REASONING_INF]:
        match = compiled_re.search(raw_output)
        if match:
            reasoning = match.group(1).strip()
            break

    # Extract final output
    final_output = raw_output
    for compiled_re in [_RE_ANNOTATION, _RE_FINAL_OUTPUT]:
        match = compiled_re.search(raw_output)
        if match:
            final_output = match.group(1).strip()
            break

    # Check for negation
    is_negated = any(neg_word in raw_output.lower() for neg_word in [
        'no ', 'not ', 'absence of', 'ruled out', 'negative', 'none',
        'no evidence', 'without', 'excluded'
    ])

    # Extract date
    date_info = None
    for compiled_re in [_RE_DATE_SLASH, _RE_DATE_ISO, _RE_DATE_FLEX]:
        match = compiled_re.search(raw_output)
        if match:
            date_info = {
                "date_value": match.group(0),
                "source": "extracted_from_text",
                "csv_date": None
            }
            break

    if not date_info and csv_date:
        date_info = {
            "date_value": csv_date,
            "source": "derived_from_csv",
            "csv_date": csv_date
        }

    return StructuredAnnotation(
        reasoning=reasoning or "Not extracted",
        final_output=final_output.strip(),
        is_negated=is_negated,
        date=date_info
    )


# ---------------------------------------------------------------------------
# Primary entry point: parse LLM output into StructuredAnnotation
# ---------------------------------------------------------------------------

def parse_structured_annotation(
    raw_output: str,
    csv_date: Optional[str] = None,
    used_guided_decoding: bool = False,
    fast_mode: bool = False,
) -> StructuredAnnotation:
    """
    Parse raw LLM output into a StructuredAnnotation.

    Uses a layered approach:
    1. Direct JSON parse (works when guided decoding produced valid JSON)
    2. Extract JSON from markdown/wrapper text (thinking blocks, code fences)
    3. Regex fallback for free-form text (legacy path)

    In fast mode, tries FastStructuredAnnotation first (only final_output,
    is_negated, date) and converts to full StructuredAnnotation.

    Args:
        raw_output: Raw text from the LLM
        csv_date: Optional CSV date to apply
        used_guided_decoding: Whether response_format was used (for logging)
        fast_mode: Whether fast mode was used (tries FastStructuredAnnotation first)

    Returns:
        StructuredAnnotation instance
    """
    # --- Layer 1: Direct JSON parse (guided decoding output) ---
    cleaned = _strip_thinking_blocks(raw_output)

    # In fast mode with guided decoding, output matches FastStructuredAnnotation schema
    if fast_mode:
        try:
            fast_ann = FastStructuredAnnotation.model_validate_json(cleaned)
            annotation = fast_ann.to_structured_annotation()
            _apply_csv_date(annotation, csv_date)
            logger.debug("Parsed fast annotation via direct JSON (Layer 1 fast)")
            return annotation
        except Exception:
            pass  # Fall through to standard parsing

    try:
        annotation = StructuredAnnotation.model_validate_json(cleaned)
        _apply_csv_date(annotation, csv_date)
        logger.debug("Parsed annotation via direct JSON (Layer 1)")
        return annotation
    except Exception:
        if used_guided_decoding:
            logger.warning(
                "Guided decoding output failed direct JSON parse — "
                "falling back to extraction. Output preview: %s",
                cleaned[:200],
            )

    # --- Layer 2: Handle unclosed thinking blocks (token budget exhaustion) ---
    if '<unused' in raw_output.lower():
        # Try markdown/JSON extraction from within the thinking block
        md_match = _RE_MARKDOWN_JSON.search(raw_output)
        if md_match:
            try:
                json_str = md_match.group(1).strip()
                parsed = json.loads(json_str)
                if isinstance(parsed, dict) and 'final_output' in parsed:
                    if csv_date and isinstance(parsed.get("date"), dict) \
                            and parsed["date"].get("source") == "derived_from_csv":
                        parsed["date"]["csv_date"] = csv_date
                    try:
                        return StructuredAnnotation(**parsed)
                    except Exception as e:
                        logger.warning("StructuredAnnotation parse failed from markdown block: %s", e)
            except json.JSONDecodeError:
                pass

        salvaged = _try_extract_from_thinking(raw_output)
        if salvaged:
            logger.info("Extracted annotation from unclosed thinking block: %s", salvaged[:80])
            return StructuredAnnotation(
                reasoning="Extracted from model thinking block (token budget was exhausted before JSON output)",
                final_output=salvaged,
                is_negated=False,
                date=None,
            )
        cleaned = _RE_THINKING_BLOCK_UNCLOSED.sub('', raw_output).strip()

    # --- Layer 3: Extract JSON from markdown/wrapper text ---
    json_str = _extract_json_string(cleaned)
    if json_str:
        # Fast mode: try FastStructuredAnnotation first
        if fast_mode:
            try:
                fast_ann = FastStructuredAnnotation.model_validate_json(json_str)
                annotation = fast_ann.to_structured_annotation()
                _apply_csv_date(annotation, csv_date)
                logger.debug("Parsed fast annotation via JSON extraction (Layer 3 fast)")
                return annotation
            except Exception:
                pass
        try:
            annotation = StructuredAnnotation.model_validate_json(json_str)
            _apply_csv_date(annotation, csv_date)
            logger.debug("Parsed annotation via JSON extraction (Layer 3)")
            return annotation
        except Exception as e:
            logger.debug("JSON extraction found string but Pydantic validation failed: %s", e)

    # --- Layer 4: Regex fallback (legacy path) ---
    logger.debug("Falling back to regex extraction (Layer 4)")
    return _regex_fallback_parse(cleaned, csv_date)


# ---------------------------------------------------------------------------
# Legacy entry point (kept for backward compatibility)
# ---------------------------------------------------------------------------

def generate_structured_annotation_fallback(
    prompt: str,
    raw_output: str,
    csv_date: Optional[str] = None
) -> StructuredAnnotation:
    """
    Fallback method to parse raw LLM output into structured format.
    Used when guided decoding is not available.

    This is a thin wrapper around parse_structured_annotation() for
    backward compatibility with existing callers.
    """
    return parse_structured_annotation(
        raw_output=raw_output,
        csv_date=csv_date,
        used_guided_decoding=False,
    )


# ---------------------------------------------------------------------------
# Per-prompt schema generation (enum-constrained final_output)
# ---------------------------------------------------------------------------

def build_per_prompt_schema(
    entity_mapping: Optional[Dict[str, Any]],
    fast_mode: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Generate a per-prompt JSON schema with enum-constrained final_output.

    Inspects entity_mapping.field_mappings to determine if ALL fields have
    value_code_mappings. If so, the prompt is a SIMPLE ENUM type and we can
    constrain final_output to only those values (+ "Not applicable").

    Returns None if the prompt cannot be constrained (template with free-text
    fields, no entity_mapping, etc.), in which case callers should fall back
    to the generic schema.
    """
    if not entity_mapping:
        return None

    field_mappings = entity_mapping.get("field_mappings", [])
    if not field_mappings:
        return None

    # Collect all valid values from value_code_mappings across field_mappings
    all_values: set = set()
    has_unconstrained_field = False

    for fm in field_mappings:
        vcm = fm.get("value_code_mappings")
        if vcm and isinstance(vcm, dict):
            all_values.update(vcm.keys())
        else:
            # This field has no enum constraint (date, measurement, free text)
            has_unconstrained_field = True

    # If ANY field is unconstrained, we can't enum-constrain final_output
    if has_unconstrained_field or not all_values:
        return None

    # Build enum list: sorted valid values + "Not applicable" as fallback
    valid_values = sorted(all_values) + ["Not applicable"]

    # Generate base schema from the appropriate Pydantic model
    import copy
    base_model = FastStructuredAnnotation if fast_mode else StructuredAnnotation
    schema = copy.deepcopy(base_model.model_json_schema())
    schema["properties"]["final_output"]["enum"] = valid_values

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "constrained_annotation",
            "schema": schema,
        }
    }


_per_prompt_schema_cache: Dict[str, Optional[Dict[str, Any]]] = {}


def get_prompt_schema(
    prompt_type: str,
    entity_mapping: Optional[Dict[str, Any]],
    fast_mode: bool = False,
) -> Dict[str, Any]:
    """
    Get the appropriate JSON schema for a prompt type.

    Returns a per-prompt constrained schema if the prompt's entity_mapping
    defines value_code_mappings for all fields (SIMPLE ENUM). Otherwise
    returns the generic ANNOTATION_JSON_SCHEMA or FAST_ANNOTATION_JSON_SCHEMA.
    """
    cache_key = f"{prompt_type}:{'fast' if fast_mode else 'std'}"

    if cache_key not in _per_prompt_schema_cache:
        constrained = build_per_prompt_schema(entity_mapping, fast_mode)
        _per_prompt_schema_cache[cache_key] = constrained

    cached = _per_prompt_schema_cache.get(cache_key)
    if cached is not None:
        return cached

    return FAST_ANNOTATION_JSON_SCHEMA if fast_mode else ANNOTATION_JSON_SCHEMA


# ---------------------------------------------------------------------------
# Legacy Outlines-based generation (deprecated, kept for reference)
# ---------------------------------------------------------------------------

try:
    import outlines
    OUTLINES_AVAILABLE = False  # Disabled: use vLLM native response_format instead
    logger.info("Outlines detected but disabled — using vLLM native guided decoding")
except ImportError:
    OUTLINES_AVAILABLE = False
except Exception:
    OUTLINES_AVAILABLE = False


def generate_structured_annotation(
    prompt: str,
    vllm_endpoint: str,
    model_name: str,
    csv_date: Optional[str] = None,
    max_new_tokens: int = 1024,
    temperature: float = 0.0
) -> Tuple[StructuredAnnotation, Optional[str]]:
    """
    Legacy Outlines-based structured generation.
    Deprecated: vLLM native response_format is preferred.
    """
    raise ImportError(
        "Outlines-based generation is deprecated. "
        "Use vLLM response_format with ANNOTATION_JSON_SCHEMA instead."
    )
