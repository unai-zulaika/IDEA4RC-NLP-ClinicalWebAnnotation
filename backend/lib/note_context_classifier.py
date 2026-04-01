"""
Note clinical context classifier.

Classifies whether a clinical note describes an initial diagnosis, recurrence,
progression, follow-up, or a mix — so downstream annotation prompts can avoid
confusing diagnosis entities with recurrence/metastasis entities.

Two classification paths:
1. Derived from existing NoteSplitResult (when history splitting already ran)
2. Lightweight LLM call (for non-split notes)
"""

import json
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Valid clinical context categories (ordered list for deterministic schema generation)
VALID_CONTEXTS_LIST = [
    "initial_diagnosis",
    "recurrence",
    "progression",
    "follow_up",
    "mixed",
    "unknown",
]
VALID_CONTEXTS = set(VALID_CONTEXTS_LIST)

# Path to the classification prompt template
_PROMPT_TEMPLATE_PATH = (
    Path(__file__).parent.parent / "data" / "system_prompts" / "classify_note_context.txt"
)

# JSON schema for guided decoding
_CLASSIFY_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "note_context_classification",
        "schema": {
            "type": "object",
            "properties": {
                "clinical_context": {
                    "type": "string",
                    "enum": VALID_CONTEXTS_LIST,
                },
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"},
            },
            "required": ["clinical_context", "confidence", "reasoning"],
        },
    },
}

# In-memory cache: (session_id, note_id) -> NoteContextResult
_context_cache: Dict[Tuple[str, str], "NoteContextResult"] = {}


@dataclass
class NoteContextResult:
    """Result of clinical context classification."""

    clinical_context: str  # One of VALID_CONTEXTS
    confidence: float  # 0.0–1.0
    reasoning: str  # Brief explanation
    source: str  # "derived_from_split" or "llm"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def get_cached_context(session_id: str, note_id: str) -> Optional[NoteContextResult]:
    """Return cached classification if available."""
    return _context_cache.get((session_id, note_id))


def clear_context_cache(session_id: Optional[str] = None) -> None:
    """Clear cached results. If session_id given, clear only that session."""
    if session_id is None:
        _context_cache.clear()
    else:
        keys_to_remove = [k for k in _context_cache if k[0] == session_id]
        for k in keys_to_remove:
            del _context_cache[k]


# ---------------------------------------------------------------------------
# Path 1: Derive from history split result
# ---------------------------------------------------------------------------

def derive_context_from_split(split_result: Any) -> NoteContextResult:
    """Derive clinical context from a NoteSplitResult without an LLM call.

    Maps the event_type values from the split result to a single clinical
    context classification.

    Args:
        split_result: A NoteSplitResult instance (from note_splitter.py)

    Returns:
        NoteContextResult with source="derived_from_split"
    """
    if not split_result or not split_result.events:
        return NoteContextResult(
            clinical_context="unknown",
            confidence=0.3,
            reasoning="No events in split result",
            source="derived_from_split",
        )

    event_types = {e.event_type for e in split_result.events}

    has_diagnosis = "diagnosis" in event_types
    has_recurrence = "recurrence" in event_types
    has_follow_up = "follow_up" in event_types
    # Treatments after diagnosis suggest recurrence context in a history note
    has_treatments = bool(
        event_types & {"chemotherapy", "radiotherapy", "other_treatment", "surgery"}
    )

    if has_diagnosis and has_recurrence:
        context = "mixed"
        confidence = 0.9
        reasoning = "Split events include both diagnosis and recurrence events"
    elif has_recurrence:
        context = "recurrence"
        confidence = 0.85
        reasoning = "Split events include recurrence event(s)"
    elif has_diagnosis and has_treatments:
        # Diagnosis + treatments in a history note usually means the note
        # covers the full clinical timeline including post-diagnosis events
        context = "mixed"
        confidence = 0.7
        reasoning = "Split events include diagnosis and treatment events spanning clinical timeline"
    elif has_diagnosis:
        context = "initial_diagnosis"
        confidence = 0.8
        reasoning = "Split events contain only diagnosis event(s)"
    elif has_follow_up and not has_treatments:
        context = "follow_up"
        confidence = 0.75
        reasoning = "Split events contain only follow-up event(s)"
    else:
        context = "unknown"
        confidence = 0.4
        reasoning = f"Could not determine context from event types: {event_types}"

    return NoteContextResult(
        clinical_context=context,
        confidence=confidence,
        reasoning=reasoning,
        source="derived_from_split",
    )


# ---------------------------------------------------------------------------
# Path 2: LLM classification
# ---------------------------------------------------------------------------

def _load_prompt_template() -> str:
    """Load the classification prompt template from disk."""
    return _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def _build_classify_prompt(note_text: str) -> str:
    """Build the full prompt for classifying a note's clinical context."""
    template = _load_prompt_template()
    return template.replace("{{note_text}}", note_text)


def _parse_classify_response(raw_response: str) -> NoteContextResult:
    """Parse the LLM response into a NoteContextResult.

    Tries direct JSON parse first, then falls back to regex extraction.
    """
    # Strip thinking blocks (MedGemma-style)
    cleaned = re.sub(
        r"<unused\d+>\w+.*?</unused\d+>\s*", "", raw_response, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(r"<unused\d+>.*$", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.strip()

    parsed = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try extracting JSON from markdown code block
        md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        if md_match:
            try:
                parsed = json.loads(md_match.group(1))
            except json.JSONDecodeError:
                pass
        # Try finding JSON object
        if parsed is None:
            obj_match = re.search(r'\{"clinical_context".*?\}', cleaned, re.DOTALL)
            if obj_match:
                try:
                    parsed = json.loads(obj_match.group(0))
                except json.JSONDecodeError:
                    pass

    if parsed is None:
        logger.warning("Failed to parse context classification response")
        return NoteContextResult(
            clinical_context="unknown",
            confidence=0.0,
            reasoning="Failed to parse LLM response",
            source="llm",
        )

    clinical_context = parsed.get("clinical_context", "unknown")
    if clinical_context not in VALID_CONTEXTS:
        logger.warning(f"Invalid clinical_context '{clinical_context}', defaulting to unknown")
        clinical_context = "unknown"

    return NoteContextResult(
        clinical_context=clinical_context,
        confidence=float(parsed.get("confidence", 0.5)),
        reasoning=parsed.get("reasoning", ""),
        source="llm",
    )


async def classify_note_context(
    note_text: str,
    vllm_client: Any,
    session_id: str = "",
    note_id: str = "",
    use_guided_decoding: bool = True,
    max_new_tokens: int = 128,
) -> NoteContextResult:
    """Classify a note's clinical context using an LLM call.

    Args:
        note_text: The full note text
        vllm_client: VLLMClient instance for LLM inference
        session_id: Session ID for caching
        note_id: Note ID for caching
        use_guided_decoding: Whether to use JSON schema guided decoding
        max_new_tokens: Max tokens for the classification response

    Returns:
        NoteContextResult with source="llm"
    """
    # Check cache first
    if session_id and note_id:
        cached = get_cached_context(session_id, note_id)
        if cached is not None:
            logger.info(f"Using cached context classification for note {note_id}")
            return cached

    # Build prompt
    prompt = _build_classify_prompt(note_text)

    # Call LLM
    try:
        kwargs: Dict[str, Any] = {}
        if use_guided_decoding:
            kwargs["response_format"] = _CLASSIFY_SCHEMA

        response = await vllm_client.agenerate(
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            temperature=0.1,
            **kwargs,
        )
        raw_response = response.get("raw", "")

    except Exception as e:
        logger.error(f"LLM context classification failed for note {note_id}: {e}")
        # Intentionally not cached so retry is possible after transient failures
        return NoteContextResult(
            clinical_context="unknown",
            confidence=0.0,
            reasoning=f"LLM call failed: {e}",
            source="llm",
        )

    result = _parse_classify_response(raw_response)

    # Cache result
    if session_id and note_id:
        _context_cache[(session_id, note_id)] = result

    logger.info(
        f"Classified note {note_id} as '{result.clinical_context}' "
        f"(confidence={result.confidence:.2f}, source={result.source})"
    )
    return result
