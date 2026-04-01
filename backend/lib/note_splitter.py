"""
Note splitter for history/anamnesis notes.

Splits a clinical history note into individual clinical events using an LLM
pre-pass, so each event can be processed independently through the annotation
pipeline.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from models.annotation_models import ClinicalEvent, NoteSplitResult

logger = logging.getLogger(__name__)

# Path to the splitting prompt template
_PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent / "data" / "system_prompts" / "split_history_note.txt"

# JSON schema for guided decoding of the split result
_SPLIT_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "note_split_result",
        "schema": {
            "type": "object",
            "properties": {
                "shared_context": {"type": "string"},
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event_text": {"type": "string"},
                            "event_type": {
                                "type": "string",
                                "enum": [
                                    "surgery", "chemotherapy", "radiotherapy",
                                    "diagnosis", "recurrence", "biopsy",
                                    "other_treatment", "follow_up", "other",
                                ],
                            },
                            "event_date": {
                                "anyOf": [{"type": "string"}, {"type": "null"}]
                            },
                        },
                        "required": ["event_text", "event_type"],
                    },
                    "maxItems": 30,
                },
            },
            "required": ["shared_context", "events"],
        },
    },
}

# In-memory cache: (session_id, note_id) -> NoteSplitResult
_split_cache: Dict[Tuple[str, str], NoteSplitResult] = {}


def clear_split_cache(session_id: Optional[str] = None) -> None:
    """Clear cached split results. If session_id given, clear only that session."""
    if session_id is None:
        _split_cache.clear()
    else:
        keys_to_remove = [k for k in _split_cache if k[0] == session_id]
        for k in keys_to_remove:
            del _split_cache[k]


def get_cached_split(session_id: str, note_id: str) -> Optional[NoteSplitResult]:
    """Get a cached split result if available."""
    return _split_cache.get((session_id, note_id))


def _load_prompt_template() -> str:
    """Load the splitting prompt template from disk."""
    return _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def _build_split_prompt(note_text: str) -> str:
    """Build the full prompt for splitting a history note."""
    template = _load_prompt_template()
    return template.replace("{{note_text}}", note_text)


def _parse_split_response(raw_response: str, original_text: str) -> NoteSplitResult:
    """Parse the LLM response into a NoteSplitResult.

    Tries direct JSON parse first, then falls back to regex extraction.
    """
    # Strip thinking blocks (MedGemma)
    cleaned = re.sub(r'<unused\d+>\w+.*?</unused\d+>\s*', '', raw_response, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<unused\d+>.*$', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.strip()

    # Try direct JSON parse
    parsed = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try extracting JSON from markdown code block
        md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.DOTALL)
        if md_match:
            try:
                parsed = json.loads(md_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding JSON object
        if parsed is None:
            obj_match = re.search(r'\{.*"events".*\}', cleaned, re.DOTALL)
            if obj_match:
                try:
                    parsed = json.loads(obj_match.group(0))
                except json.JSONDecodeError:
                    pass

    if parsed is None:
        logger.warning("Failed to parse split response, returning unsplit note")
        return NoteSplitResult(
            shared_context="",
            events=[ClinicalEvent(event_text=original_text, event_type="other", event_date=None)],
            original_text=original_text,
            was_split=False,
        )

    # Validate and build result
    shared_context = parsed.get("shared_context", "")
    raw_events = parsed.get("events", [])

    if not isinstance(raw_events, list) or len(raw_events) == 0:
        logger.warning("No events in split response, returning unsplit note")
        return NoteSplitResult(
            shared_context=shared_context,
            events=[ClinicalEvent(event_text=original_text, event_type="other", event_date=None)],
            original_text=original_text,
            was_split=False,
        )

    events = []
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        event_text = raw_event.get("event_text", "").strip()
        if not event_text:
            continue
        events.append(ClinicalEvent(
            event_text=event_text,
            event_type=raw_event.get("event_type", "other"),
            event_date=raw_event.get("event_date"),
        ))

    if len(events) == 0:
        return NoteSplitResult(
            shared_context=shared_context,
            events=[ClinicalEvent(event_text=original_text, event_type="other", event_date=None)],
            original_text=original_text,
            was_split=False,
        )

    was_split = len(events) > 1
    return NoteSplitResult(
        shared_context=shared_context,
        events=events,
        original_text=original_text,
        was_split=was_split,
    )


async def split_history_note(
    note_text: str,
    vllm_client: Any,
    session_id: str = "",
    note_id: str = "",
    use_guided_decoding: bool = True,
    max_new_tokens: int = 4096,
) -> NoteSplitResult:
    """Split a history note into individual clinical events using LLM.

    Args:
        note_text: The full history note text
        vllm_client: VLLMClient instance for LLM inference
        session_id: Session ID for caching
        note_id: Note ID for caching
        use_guided_decoding: Whether to use JSON schema guided decoding
        max_new_tokens: Max tokens for the splitting response

    Returns:
        NoteSplitResult with shared_context and list of ClinicalEvent
    """
    # Check cache first
    if session_id and note_id:
        cached = get_cached_split(session_id, note_id)
        if cached is not None:
            logger.info(f"Using cached split result for note {note_id}")
            return cached

    # Build prompt
    prompt = _build_split_prompt(note_text)

    # Call LLM
    try:
        kwargs: Dict[str, Any] = {}
        if use_guided_decoding:
            kwargs["response_format"] = _SPLIT_SCHEMA

        response = await vllm_client.agenerate(
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            temperature=0.1,
            **kwargs,
        )
        raw_response = response.get("raw", "")

    except Exception as e:
        logger.error(f"LLM splitting failed for note {note_id}: {e}")
        return NoteSplitResult(
            shared_context="",
            events=[ClinicalEvent(event_text=note_text, event_type="other", event_date=None)],
            original_text=note_text,
            was_split=False,
        )

    # Parse response
    result = _parse_split_response(raw_response, note_text)

    # Cache result
    if session_id and note_id:
        _split_cache[(session_id, note_id)] = result

    if result.was_split:
        logger.info(
            f"Split note {note_id} into {len(result.events)} events: "
            f"{[e.event_type for e in result.events]}"
        )
    else:
        logger.info(f"Note {note_id} was not split (single event or split failed)")

    return result


def build_sub_note(shared_context: str, event: ClinicalEvent) -> str:
    """Build a processable sub-note by prepending shared context to an event.

    Args:
        shared_context: Patient-level context (demographics, diagnosis)
        event: The clinical event

    Returns:
        Combined text ready for annotation processing
    """
    if shared_context.strip():
        return f"{shared_context.strip()}\n\n{event.event_text}"
    return event.event_text
