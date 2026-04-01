"""
Result aggregator for multi-event annotation results.

Merges multiple AnnotationResult objects (from split sub-notes or multiple
chunks) into a single AnnotationResult with multiple values, applying
deduplication based on normalized text and dates.
"""

import re
import unicodedata
from typing import List, Optional

from models.schemas import AnnotationResult, AnnotationValue, EvidenceSpan
from models.annotation_models import MultiValueInfo


def _normalize_for_dedup(text: str) -> str:
    """Normalize text for deduplication comparison."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower().strip()
    # Remove trailing punctuation
    text = text.rstrip(".,;:!? ")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_date(date_str: str) -> Optional[str]:
    """Normalize a date string to YYYY-MM-DD for comparison."""
    if not date_str:
        return None

    date_str = date_str.strip().rstrip("r. ")

    # DD/MM/YYYY or DD.MM.YYYY
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", date_str)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"

    # YYYY-MM-DD (already normalized)
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"

    # MM/YYYY or MM.YYYY
    m = re.match(r"(\d{1,2})[./](\d{4})", date_str)
    if m:
        return f"{m.group(2)}-{m.group(1).zfill(2)}"

    # YYYY only
    m = re.match(r"(\d{4})$", date_str)
    if m:
        return m.group(1)

    return date_str


def _extract_date_from_annotation(annotation_text: str) -> Optional[str]:
    """Try to extract a date from annotation text for dedup purposes."""
    # Look for common date patterns
    m = re.search(r"\d{1,2}[./]\d{1,2}[./]\d{4}", annotation_text)
    if m:
        return _normalize_date(m.group(0))
    m = re.search(r"\d{4}-\d{1,2}-\d{1,2}", annotation_text)
    if m:
        return _normalize_date(m.group(0))
    m = re.search(r"\d{1,2}[./]\d{4}", annotation_text)
    if m:
        return _normalize_date(m.group(0))
    return None


def _is_null_result(annotation_text: str) -> bool:
    """Check if an annotation result is effectively null/empty."""
    if not annotation_text:
        return True
    normalized = _normalize_for_dedup(annotation_text)
    null_patterns = {
        "unknown", "n/a", "not mentioned", "not found", "not available",
        "not stated", "not provided", "not specified", "not documented",
        "not applicable", "information not available", "information not available in the note",
        "nessuno", "non specificato", "non disponibile",
    }
    return normalized in null_patterns


def _are_duplicates(text1: str, text2: str) -> bool:
    """Check if two annotation texts are duplicates."""
    n1 = _normalize_for_dedup(text1)
    n2 = _normalize_for_dedup(text2)

    # Exact match after normalization
    if n1 == n2:
        return True

    # Check if one contains the other (substring dedup)
    if len(n1) > 10 and len(n2) > 10:
        if n1 in n2 or n2 in n1:
            return True

    # Date-based dedup: if both have dates and dates match,
    # and the rest is structurally similar, consider them duplicates
    date1 = _extract_date_from_annotation(text1)
    date2 = _extract_date_from_annotation(text2)
    if date1 and date2 and date1 == date2:
        # Remove dates and compare remaining text
        remaining1 = re.sub(r"\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{1,2}-\d{1,2}", "", n1).strip()
        remaining2 = re.sub(r"\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{1,2}-\d{1,2}", "", n2).strip()
        if remaining1 == remaining2:
            return True

    return False


def aggregate_results(
    results: List[AnnotationResult],
    prompt_type: str,
    total_events: int = 0,
) -> AnnotationResult:
    """Aggregate multiple AnnotationResult objects into one with multiple values.

    Args:
        results: List of AnnotationResult from sub-note processing
        prompt_type: The prompt type being processed
        total_events: Total events detected in the original note

    Returns:
        Single AnnotationResult with deduplicated values in values[]
    """
    if not results:
        return AnnotationResult(
            prompt_type=prompt_type,
            annotation_text="No results extracted",
            values=[],
            evidence_spans=[],
            reasoning=None,
            is_negated=None,
            date_info=None,
            evidence_text=None,
            raw_prompt="",
            raw_response="",
            status="error",
            multi_value_info=MultiValueInfo(
                was_split=True,
                total_events_detected=total_events,
                unique_values_extracted=0,
                split_method="llm",
            ).model_dump(),
        )

    if len(results) == 1:
        result = results[0]
        result.multi_value_info = MultiValueInfo(
            was_split=True,
            total_events_detected=total_events,
            unique_values_extracted=1 if not _is_null_result(result.annotation_text) else 0,
            split_method="llm",
        ).model_dump()
        return result

    # Filter out null/empty results
    valid_results = [r for r in results if not _is_null_result(r.annotation_text)]

    if not valid_results:
        # All results were null — return the first one
        result = results[0]
        result.multi_value_info = MultiValueInfo(
            was_split=True,
            total_events_detected=total_events,
            unique_values_extracted=0,
            split_method="llm",
        ).model_dump()
        return result

    # Deduplicate
    unique_results: List[AnnotationResult] = []
    for r in valid_results:
        is_dup = False
        for u in unique_results:
            if _are_duplicates(r.annotation_text, u.annotation_text):
                is_dup = True
                # Keep the one with more information (longer text)
                if len(r.annotation_text) > len(u.annotation_text):
                    unique_results[unique_results.index(u)] = r
                break
        if not is_dup:
            unique_results.append(r)

    # Sort by date if possible (chronological order)
    def _sort_key(r: AnnotationResult):
        date = _extract_date_from_annotation(r.annotation_text)
        return date or "9999"

    unique_results.sort(key=_sort_key)

    # Build aggregated result
    primary = unique_results[0]

    # Collect all values
    all_values: List[AnnotationValue] = []
    all_evidence: List[EvidenceSpan] = []
    all_reasoning_parts: List[str] = []

    for r in unique_results:
        # Add annotation_text as a value
        all_values.append(AnnotationValue(
            value=r.annotation_text,
            evidence_spans=r.evidence_spans or [],
            reasoning=r.reasoning,
        ))
        if r.evidence_spans:
            all_evidence.extend(r.evidence_spans)
        if r.reasoning:
            all_reasoning_parts.append(r.reasoning)

    # Combine reasoning
    combined_reasoning = " | ".join(all_reasoning_parts) if all_reasoning_parts else None
    if combined_reasoning and len(combined_reasoning) > 2000:
        combined_reasoning = combined_reasoning[:1997] + "..."

    return AnnotationResult(
        prompt_type=prompt_type,
        annotation_text=primary.annotation_text,
        values=all_values,
        confidence_score=primary.confidence_score,
        evidence_spans=all_evidence,
        reasoning=combined_reasoning,
        is_negated=primary.is_negated,
        date_info=primary.date_info,
        evidence_text=primary.evidence_text,
        raw_prompt=primary.raw_prompt,
        raw_response=" ||| ".join(r.raw_response or "" for r in unique_results),
        status="success" if any(r.status == "success" for r in unique_results) else primary.status,
        icdo3_code=primary.icdo3_code,
        timing_breakdown=primary.timing_breakdown,
        derived_field_values=primary.derived_field_values,
        hallucination_flags=primary.hallucination_flags,
        multi_value_info=MultiValueInfo(
            was_split=True,
            total_events_detected=total_events,
            unique_values_extracted=len(unique_results),
            split_method="llm",
        ).model_dump(),
    )
