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


# --- Bare value re-wrapping ---
# Regex to extract the output format line from a prompt template
_RE_OUTPUT_FORMAT = re.compile(
    r'Output format[^:\n]*:\s*(?:Annotation:\s*)?(.+?)(?:\n|$)',
    re.IGNORECASE,
)
# Regex to find a bracketed placeholder with enumerated options (pipe or slash separated)
_RE_ENUM_PLACEHOLDER = re.compile(r'\[([^\[\]]+)\]')


def _parse_template_format(prompt_template: str) -> Optional[tuple]:
    """
    Parse the output format line from a prompt template.

    Returns (label, options) where:
      - label: the text before the placeholder (e.g., "Tumor depth")
      - options: list of enumerated values (e.g., ["superficial", "deep"])
    Returns None if the format can't be parsed or has multiple/free-text placeholders.
    """
    m = _RE_OUTPUT_FORMAT.search(prompt_template)
    if not m:
        return None

    format_line = m.group(1).strip().rstrip('.')

    # Find all bracketed placeholders
    placeholders = _RE_ENUM_PLACEHOLDER.findall(format_line)
    if len(placeholders) != 1:
        # Multiple placeholders or none — too complex to re-wrap
        return None

    placeholder_text = placeholders[0]

    # Check if it's enumerated options (pipe | or slash / separated)
    if '|' in placeholder_text:
        options = [o.strip() for o in placeholder_text.split('|')]
    elif '/' in placeholder_text:
        options = [o.strip() for o in placeholder_text.split('/')]
    else:
        # Single value placeholder like [value] — can't re-wrap
        return None

    # Filter out generic placeholders
    generic = {'value', 'date', 'select', 'put', 'provide', 'choose'}
    if all(o.lower() in generic for o in options):
        return None

    # Extract the label: everything before the placeholder bracket
    bracket_start = format_line.index('[')
    label = format_line[:bracket_start].strip().rstrip(':').strip()

    return (label, options) if label else None


def re_wrap_bare_value(annotation_text: str, prompt_template: str) -> str:
    """
    Re-wrap a bare LLM output value into the expected template format.

    If the LLM outputs just "deep" but the template expects "Tumor depth: deep.",
    this function reconstructs the full format.

    Args:
        annotation_text: The normalized annotation text (may be a bare value)
        prompt_template: The raw prompt template text (used to extract expected format)

    Returns:
        Re-wrapped annotation text, or original if no re-wrapping needed
    """
    if not annotation_text or not prompt_template:
        return annotation_text

    text = annotation_text.strip()

    parsed = _parse_template_format(prompt_template)
    if not parsed:
        return annotation_text

    label, options = parsed

    # If the text already contains the label prefix, no re-wrapping needed
    if label.lower() in text.lower():
        return annotation_text

    # Check if text matches one of the enumerated options (case-insensitive)
    text_lower = text.lower().rstrip('.')
    for option in options:
        if text_lower == option.lower():
            return f"{label}: {option}."

    # Also re-wrap absence indicators with the label
    if _is_absence_indicator(text):
        existing_label = _extract_label(text)
        if not existing_label:
            return f"{label}: {text}"

    return annotation_text


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

