"""
Annotation normalization utilities.
Standardizes absence indicators and normalizes annotation formats.
"""

import re
from typing import Optional


# Standard absence indicator - use this consistently
STANDARD_ABSENCE_INDICATOR = "Not applicable"

# Patterns that indicate absence (for detection)
ABSENCE_PATTERNS = [
    r'\bnot\s+(specified|available|applicable|mentioned|present|found)\b',
    r'\bunknown\b',
    r'\bno\s+(information|data|result|finding|value)\b',
    r'\binformation\s+not\s+available\b',
    r'\bnot\s+available\s+in\s+the\s+note\b',
    r'\[select\s+(result|value|intent|regimen|reason|where|date)\b',  # Placeholder values
    r'^\[.*\]$',  # Placeholder in brackets
]


def normalize_absence_indicator(annotation_text: str, prompt_type: Optional[str] = None) -> str:
    """
    Normalize absence indicators in annotation text to a standard format.
    
    This function:
    1. Detects if the annotation indicates absence
    2. Normalizes it to the standard format: "[Label]: Not applicable" or "Not applicable"
    
    Args:
        annotation_text: The annotation text to normalize
        prompt_type: Optional prompt type for context-specific normalization
    
    Returns:
        Normalized annotation text with standardized absence indicator
    """
    if not annotation_text or not annotation_text.strip():
        return ""
    
    text = annotation_text.strip()
    
    # Check if this is an absence indicator
    is_absence = _is_absence_indicator(text)
    
    if not is_absence:
        return text  # Not an absence, return as-is
    
    # Extract label from structured format (e.g., "Tumor depth: Not specified" -> "Tumor depth")
    label = _extract_label(text)
    
    if label:
        # Structured format: "Label: Not applicable"
        return f"{label}: {STANDARD_ABSENCE_INDICATOR}"
    else:
        # Simple format: "Not applicable"
        return STANDARD_ABSENCE_INDICATOR


def _is_absence_indicator(text: str) -> bool:
    """
    Check if text indicates absence.
    
    Args:
        text: Text to check
    
    Returns:
        True if text indicates absence
    """
    if not text:
        return True
    
    normalized = text.lower().strip()
    
    # Check against absence patterns
    for pattern in ABSENCE_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True
    
    return False


def _extract_label(text: str) -> Optional[str]:
    """
    Extract label from structured annotation format.
    
    Examples:
        "Tumor depth: Not specified" -> "Tumor depth"
        "Biopsy grading: Unknown" -> "Biopsy grading"
        "Not specified" -> None
    
    Args:
        text: Annotation text
    
    Returns:
        Label if found, None otherwise
    """
    # Pattern: "Label: Value" or "Label Value"
    colon_match = re.search(r'^(.+?):\s*.+$', text)
    if colon_match:
        label = colon_match.group(1).strip()
        # Verify it's a reasonable label (not just an absence indicator)
        if not _is_absence_indicator(label):
            return label
    
    return None


def normalize_annotation_output(
    final_output: str,
    prompt_type: Optional[str] = None,
    normalize_absence: bool = True
) -> str:
    """
    Normalize annotation output, including absence indicators.
    
    Args:
        final_output: The final_output field from StructuredAnnotation
        prompt_type: Optional prompt type for context
        normalize_absence: Whether to normalize absence indicators (default: True)
    
    Returns:
        Normalized annotation text
    """
    if not final_output:
        return ""
    
    if normalize_absence:
        return normalize_absence_indicator(final_output, prompt_type)
    
    return final_output.strip()

