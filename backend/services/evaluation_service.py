"""
Evaluation service for comparing predicted vs expected annotations.
Handles special cases for "no annotation" scenarios.

Provides two evaluation modes:
1. Prompt-level evaluation: Compares entire annotation strings
2. Field-level evaluation: Template-aware per-value comparison
"""

import re
from typing import Dict, Optional, List
from lib.evaluation_engine import (
    evaluate_annotation as base_evaluate_annotation,
    normalize_string,
    evaluate_per_field,
    extract_template_placeholders,
    extract_dates,
    merge_dates_from_template_and_extracted,
    extract_values_from_annotation
)

# Pre-compiled "no annotation" patterns (avoids re-compiling on every call)
_NO_ANNOTATION_PATTERNS = [
    re.compile(r'\b(none|n/a|na)\b', re.IGNORECASE),
    re.compile(r'\bno\s+(annotation|information|data|result|finding|value)\b', re.IGNORECASE),
    re.compile(r'\bnot\s+(applicable|available|found|specified|mentioned|present|applicable)\b', re.IGNORECASE),
    re.compile(r'\bno\s+annotation\s+expected\b', re.IGNORECASE),
    re.compile(r'\binformation\s+not\s+available\b', re.IGNORECASE),
    re.compile(r'\bno\s+relevant\s+information\b', re.IGNORECASE),
    re.compile(r'\bunknown\b', re.IGNORECASE),
    re.compile(r'\bnot\s+available\s+in\s+the\s+note\b', re.IGNORECASE),
    re.compile(r'\bselect\s+(result|value|intent|regimen|reason|where|date)\b', re.IGNORECASE),
    re.compile(r'^\[.*\]$', re.IGNORECASE),
    re.compile(r'^$', re.IGNORECASE),
]


def is_no_annotation_indicator(text: str) -> bool:
    """
    Check if the text indicates "no annotation expected" or similar.
    
    Handles both:
    - Simple absence indicators: "none", "not specified", etc.
    - Structured annotations: "Tumor depth: Not specified", "Biopsy grading: Unknown", etc.
    
    Patterns that indicate no annotation:
    - "none", "no", "not applicable", "n/a", "na"
    - "no annotation", "no information", "not found"
    - "not specified", "unknown", "not available"
    - Empty or whitespace-only strings
    """
    if not text:
        return True
    
    normalized = normalize_string(text)
    
    # Extract value from structured annotations (format: "Label: Value" or "Label Value")
    # Try to extract the value part after colon or as the last significant word/phrase
    value_part = normalized
    
    # Check for structured format: "label: value" or "label value"
    # Extract the value part after the colon
    colon_match = re.search(r':\s*(.+)$', normalized)
    if colon_match:
        value_part = colon_match.group(1).strip()
    
    # If no colon, try to extract the last meaningful phrase (after common prefixes)
    if value_part == normalized:
        # Try patterns like "annotation: value" or "tumor depth value"
        # Extract last 1-3 words as potential value
        words = normalized.split()
        if len(words) > 2:
            # Take last 1-3 words as potential value
            value_part = ' '.join(words[-3:])
    
    # Check both the full normalized text and the extracted value part
    texts_to_check = [normalized, value_part]

    for check_text in texts_to_check:
        for pattern in _NO_ANNOTATION_PATTERNS:
            if pattern.search(check_text):
                return True

    return False


def evaluate_annotation_with_special_cases(
    expected: str,
    predicted: str,
    note_id: Optional[str] = None,
    prompt_type: Optional[str] = None
) -> Dict:
    """
    Evaluate annotation with special handling for "no annotation" cases.
    
    Special cases:
    1. Both expected and predicted are empty → exact match
    2. Expected is empty and predicted indicates "no annotation" → exact match
    3. Expected is empty and predicted is empty/whitespace → exact match
    4. Expected is empty and predicted has content → mismatch (false positive)
    5. Expected has content and predicted is empty/indicates "no annotation" → mismatch (false negative)
    
    Args:
        expected: Expected annotation string (can be empty)
        predicted: Predicted/LLM output string
        note_id: Optional note ID
        prompt_type: Optional prompt type
    
    Returns:
        Dictionary with evaluation results including special case handling
    """
    # Normalize inputs
    expected = expected.strip() if expected else ""
    predicted = predicted.strip() if predicted else ""
    
    # Check if expected indicates "no annotation"
    expected_is_empty = not expected or is_no_annotation_indicator(expected)
    
    # Check if predicted indicates "no annotation"
    predicted_is_empty = not predicted or is_no_annotation_indicator(predicted)
    
    # Special case 1: Both empty → match
    if expected_is_empty and predicted_is_empty:
        return {
            'note_id': note_id,
            'prompt_type': prompt_type,
            'exact_match': True,
            'similarity_score': 1.0,
            'high_similarity': True,
            'overall_match': True,
            'expected_annotation': expected or '[NO EXPECTED ANNOTATION]',
            'predicted_annotation': predicted or '[NO PREDICTION]',
            'total_values': 0,
            'values_matched': 0,
            'value_match_rate': None,
            'value_details': [],
            'match_type': 'both_empty'  # Special case indicator
        }
    
    # Special case 2 is already handled above (both empty)
    
    # Special case 3: Expected empty, predicted has content → false positive (mismatch)
    if expected_is_empty and not predicted_is_empty:
        return {
            'note_id': note_id,
            'prompt_type': prompt_type,
            'exact_match': False,
            'similarity_score': 0.0,
            'high_similarity': False,
            'overall_match': False,
            'expected_annotation': expected or '[NO EXPECTED ANNOTATION]',
            'predicted_annotation': predicted,
            'total_values': 0,
            'values_matched': 0,
            'value_match_rate': None,
            'value_details': [],
            'match_type': 'false_positive'  # Special case indicator
        }
    
    # Special case 4: Expected has content, predicted empty/indicates "no annotation" → false negative (mismatch)
    if not expected_is_empty and predicted_is_empty:
        return {
            'note_id': note_id,
            'prompt_type': prompt_type,
            'exact_match': False,
            'similarity_score': 0.0,
            'high_similarity': False,
            'overall_match': False,
            'expected_annotation': expected,
            'predicted_annotation': predicted or '[NO PREDICTION]',
            'total_values': 0,
            'values_matched': 0,
            'value_match_rate': None,
            'value_details': [],
            'match_type': 'false_negative'  # Special case indicator
        }
    
    # Both have content - use standard evaluation
    result = base_evaluate_annotation(
        expected=expected,
        predicted=predicted,
        note_id=note_id,
        prompt_type=prompt_type
    )

    # Add match_type for standard evaluation
    if result['overall_match']:
        result['match_type'] = 'match'
    else:
        result['match_type'] = 'mismatch'

    return result


def extract_template_format_from_prompt(template: str) -> Optional[str]:
    """
    Extract the output format line(s) from a prompt template.

    Looks for patterns like:
    - "Output strictly in the following format:"
    - "Formats:"
    - Lines containing placeholders like [provide date], [select ...]

    Args:
        template: Full prompt template string

    Returns:
        The output format string or None if not found
    """
    if not template:
        return None

    lines = template.split('\n')
    format_lines = []
    in_format_section = False

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        line_lower = line_stripped.lower()

        # Detect format section start
        if ('output strictly' in line_lower or
            'formats:' in line_lower or
            'format:' in line_lower and 'output' in line_lower):
            in_format_section = True
            continue

        # In format section, collect lines with placeholders
        if in_format_section:
            # Stop at next section header
            if line_stripped.startswith('#') or line_stripped.startswith('Notes:'):
                break
            # Check if line has placeholders
            if '[' in line_stripped and ']' in line_stripped:
                format_lines.append(line_stripped)
            elif line_stripped and not format_lines:
                # First non-empty line after format header
                format_lines.append(line_stripped)
            elif not line_stripped and format_lines:
                # Empty line after collecting formats - might be end
                break

        # Also check for standalone format lines
        if not in_format_section and '[' in line_stripped:
            # Check if this looks like an output format
            placeholders = re.findall(r'\[(?:provide|put|select)[^\]]+\]', line_stripped, re.IGNORECASE)
            if placeholders:
                format_lines.append(line_stripped)

    if format_lines:
        return '\n'.join(format_lines)

    return None


def evaluate_annotation_with_template(
    expected: str,
    predicted: str,
    template: str,
    note_id: Optional[str] = None,
    prompt_type: Optional[str] = None
) -> Dict:
    """
    Comprehensive evaluation including both prompt-level and field-level analysis.

    This function:
    1. Performs standard prompt-level evaluation (overall match, similarity)
    2. Extracts the output format from the template
    3. Performs field-level evaluation for each placeholder
    4. Merges dates from template placeholders and auto-extraction

    Args:
        expected: Expected annotation string
        predicted: Predicted/LLM output string
        template: Full prompt template string
        note_id: Optional note ID for tracking
        prompt_type: Optional prompt type for tracking

    Returns:
        Dictionary with both prompt-level and field-level evaluation results
    """
    # First, perform standard evaluation
    result = evaluate_annotation_with_special_cases(
        expected=expected,
        predicted=predicted,
        note_id=note_id,
        prompt_type=prompt_type
    )

    # Extract output format from template
    template_format = extract_template_format_from_prompt(template)

    if template_format:
        # Perform field-level evaluation
        field_evaluation = evaluate_per_field(
            expected=expected,
            predicted=predicted,
            template_format=template_format,
            note_id=note_id,
            prompt_type=prompt_type
        )

        # Add field evaluation to result
        result['field_evaluation'] = field_evaluation

        # Merge dates if template has date placeholders
        if field_evaluation.get('field_evaluation_available'):
            # Get dates from field extraction
            template_dates = []
            for field_result in field_evaluation.get('field_results', []):
                if field_result.get('field_type') == 'date':
                    if field_result.get('predicted'):
                        template_dates.append(field_result['predicted'])

            # Get auto-extracted dates
            auto_dates = extract_dates(predicted)

            # Merge dates
            merged_dates = merge_dates_from_template_and_extracted(
                predicted, template_dates, auto_dates
            )

            result['merged_dates'] = merged_dates
    else:
        result['field_evaluation'] = {
            'field_evaluation_available': False,
            'reason': 'Could not extract output format from template'
        }

    return result


def get_field_level_summary(evaluation_result: Dict) -> Dict:
    """
    Generate a user-friendly summary of field-level evaluation results.

    Args:
        evaluation_result: Full evaluation result from evaluate_annotation_with_template

    Returns:
        Summary dictionary with key metrics and feedback
    """
    field_eval = evaluation_result.get('field_evaluation', {})

    if not field_eval.get('field_evaluation_available'):
        return {
            'available': False,
            'reason': field_eval.get('reason', 'Field evaluation not available')
        }

    field_results = field_eval.get('field_results', [])

    # Categorize results
    correct_fields = []
    incorrect_fields = []
    extracted_fields = []  # Where expected was placeholder but we extracted value

    for field in field_results:
        if field['match']:
            if field.get('match_method') == 'extraction_success':
                extracted_fields.append(field)
            else:
                correct_fields.append(field)
        else:
            incorrect_fields.append(field)

    # Generate feedback messages
    feedback = []

    if correct_fields:
        correct_names = [f['field_name'] for f in correct_fields]
        feedback.append({
            'type': 'success',
            'message': f"Correct values: {', '.join(correct_names)}"
        })

    if extracted_fields:
        extracted_names = [f['field_name'] for f in extracted_fields]
        feedback.append({
            'type': 'info',
            'message': f"Successfully extracted: {', '.join(extracted_names)}"
        })

    if incorrect_fields:
        for field in incorrect_fields:
            if field.get('match_method') == 'extraction_failed':
                feedback.append({
                    'type': 'error',
                    'message': f"Failed to extract '{field['field_name']}': expected '{field['expected']}'"
                })
            elif field['field_type'] == 'date':
                feedback.append({
                    'type': 'warning',
                    'message': f"Date mismatch in '{field['field_name']}': expected '{field['expected']}', got '{field['predicted']}'"
                })
            else:
                feedback.append({
                    'type': 'error',
                    'message': f"Mismatch in '{field['field_name']}': expected '{field['expected']}', got '{field['predicted']}'"
                })

    return {
        'available': True,
        'total_fields': field_eval.get('total_fields', 0),
        'fields_matched': field_eval.get('fields_matched', 0),
        'field_match_rate': field_eval.get('field_match_rate', 0),
        'overall_field_match': field_eval.get('overall_field_match', False),
        'correct_fields': len(correct_fields),
        'extracted_fields': len(extracted_fields),
        'incorrect_fields': len(incorrect_fields),
        'feedback': feedback,
        'field_details': field_results
    }

