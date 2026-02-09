"""
Evaluation Engine for LLM Outputs

Compares LLM outputs with expected annotations using:
1. Exact match (case-insensitive, Unicode normalized)
2. Per-value extraction for multi-field templates
3. Cosine similarity (TF-IDF) as fallback metric
"""

import re
import unicodedata
from typing import Dict, List, Tuple, Optional
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def normalize_string(text: str, remove_trailing_punctuation: bool = False) -> str:
    """
    Normalize string for comparison: Unicode NFKC, lowercase, strip.
    
    Args:
        text: Input string (or any type that can be converted to string)
        remove_trailing_punctuation: If True, remove trailing periods, commas, etc. for more flexible matching
    
    Returns:
        Normalized string
    """
    if text is None:
        return ""
    # Convert to string first (handles floats, ints, etc.)
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return ""
    # Unicode normalization (NFKC)
    normalized = unicodedata.normalize('NFKC', text)
    # Lowercase and strip
    normalized = normalized.lower().strip()
    # Optionally remove trailing punctuation for more flexible matching
    if remove_trailing_punctuation:
        normalized = re.sub(r'[.,;:!?]+$', '', normalized).strip()
    return normalized


def exact_match(expected: str, predicted: str, flexible_punctuation: bool = True) -> bool:
    """
    Check if two strings match exactly after normalization.
    
    Args:
        expected: Expected annotation string
        predicted: Predicted/LLM output string
        flexible_punctuation: If True, compare with and without trailing punctuation
    
    Returns:
        True if strings match exactly after normalization
    """
    # First try strict normalization
    norm_expected = normalize_string(expected)
    norm_predicted = normalize_string(predicted)
    
    # Handle empty cases
    if not norm_expected and not norm_predicted:
        return True  # Both empty = match
    if not norm_expected or not norm_predicted:
        return False  # One empty, one not = mismatch
    
    # Strict match
    if norm_expected == norm_predicted:
        return True
    
    # If flexible_punctuation is enabled, try comparing without trailing punctuation
    if flexible_punctuation:
        norm_expected_flex = normalize_string(expected, remove_trailing_punctuation=True)
        norm_predicted_flex = normalize_string(predicted, remove_trailing_punctuation=True)
        if norm_expected_flex == norm_predicted_flex and norm_expected_flex:  # Only if both are non-empty
            return True
    
    return False


def cosine_similarity_score(expected: str, predicted: str) -> float:
    """
    Calculate TF-IDF cosine similarity between two strings.
    
    Args:
        expected: Expected annotation string
        predicted: Predicted/LLM output string
    
    Returns:
        Cosine similarity score (0.0 to 1.0)
    """
    if not expected and not predicted:
        return 1.0
    if not expected or not predicted:
        return 0.0
    
    try:
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform([expected, predicted])
        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        return float(similarity)
    except Exception:
        # Fallback to exact match if vectorization fails
        return 1.0 if exact_match(expected, predicted) else 0.0


def extract_dates(text: str) -> List[str]:
    """
    Extract dates from text using common date patterns.
    
    Args:
        text: Input text
    
    Returns:
        List of extracted date strings
    """
    date_patterns = [
        r'\d{2}/\d{2}/\d{4}',  # DD/MM/YYYY
        r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
        r'\d{1,2}/\d{1,2}/\d{4}',  # D/M/YYYY or DD/M/YYYY
    ]
    
    dates = []
    for pattern in date_patterns:
        matches = re.findall(pattern, text)
        dates.extend(matches)
    
    return list(set(dates))  # Remove duplicates


def extract_numbers_with_units(text: str) -> List[Tuple[str, str]]:
    """
    Extract numbers with units (e.g., "110 mm", "50 Gy", "34 years").
    
    Args:
        text: Input text
    
    Returns:
        List of (value, unit) tuples
    """
    # Pattern: number (with optional decimal) + unit
    pattern = r'(\d+\.?\d*)\s*(mm|cm|Gy|HPF|years|years\.|cycles|fractions|fr\.?|mg/m2)'
    matches = re.findall(pattern, text, re.IGNORECASE)
    return [(value, unit.lower()) for value, unit in matches]


def extract_key_value_pairs(text: str) -> List[Tuple[str, str]]:
    """
    Extract key-value pairs like "key: value" from text.
    
    Args:
        text: Input text
    
    Returns:
        List of (key, value) tuples
    """
    # Pattern: key: value or key [value]
    patterns = [
        r'([^:]+):\s*([^\n,;]+)',  # key: value
        r'([^\[]+)\[\s*([^\]]+)\]',  # key [value]
    ]
    
    pairs = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for key, value in matches:
            key = key.strip()
            value = value.strip()
            if key and value:
                pairs.append((key, value))
    
    return pairs


def extract_enumeration_values(text: str) -> List[str]:
    """
    Extract values from comma or semicolon-separated lists.
    
    Args:
        text: Input text
    
    Returns:
        List of extracted values
    """
    # Try semicolon first (less common in normal text)
    if ';' in text:
        values = [v.strip() for v in text.split(';') if v.strip()]
        if len(values) > 1:
            return values
    
    # Try comma-separated (but avoid splitting single sentences)
    if ',' in text:
        values = [v.strip() for v in text.split(',')]
        # Only treat as enumeration if values are short (likely not a sentence)
        if len(values) > 1 and all(len(v) < 50 for v in values):
            return values
    
    return []


def extract_structured_values(text: str) -> Dict[str, List]:
    """
    Extract structured values from annotation text.
    
    Args:
        text: Input annotation text
    
    Returns:
        Dictionary with extracted values by type
    """
    return {
        'dates': extract_dates(text),
        'numbers_with_units': extract_numbers_with_units(text),
        'key_value_pairs': extract_key_value_pairs(text),
        'enumerations': extract_enumeration_values(text)
    }


def compare_values(expected_values: Dict[str, List], predicted_values: Dict[str, List]) -> Dict:
    """
    Compare extracted values from expected and predicted annotations.
    
    Args:
        expected_values: Extracted values from expected annotation
        predicted_values: Extracted values from predicted annotation
    
    Returns:
        Dictionary with comparison results
    """
    value_details = []
    total_values = 0
    values_matched = 0
    
    # Compare dates
    exp_dates = set(expected_values.get('dates', []))
    pred_dates = set(predicted_values.get('dates', []))
    if exp_dates or pred_dates:
        total_values += 1
        match = exp_dates == pred_dates
        if match:
            values_matched += 1
        value_details.append({
            'field': 'dates',
            'expected': ', '.join(sorted(exp_dates)) if exp_dates else '',
            'predicted': ', '.join(sorted(pred_dates)) if pred_dates else '',
            'match': match
        })
    
    # Compare numbers with units
    exp_numbers = set(expected_values.get('numbers_with_units', []))
    pred_numbers = set(predicted_values.get('numbers_with_units', []))
    if exp_numbers or pred_numbers:
        total_values += 1
        match = exp_numbers == pred_numbers
        if match:
            values_matched += 1
        value_details.append({
            'field': 'numbers_with_units',
            'expected': str(list(exp_numbers)) if exp_numbers else '',
            'predicted': str(list(pred_numbers)) if pred_numbers else '',
            'match': match
        })
    
    # Compare key-value pairs (normalized comparison)
    exp_pairs = expected_values.get('key_value_pairs', [])
    pred_pairs = predicted_values.get('key_value_pairs', [])
    if exp_pairs or pred_pairs:
        # Normalize pairs for comparison
        exp_pairs_normalized = {
            (normalize_string(k), normalize_string(v)) 
            for k, v in exp_pairs
        }
        pred_pairs_normalized = {
            (normalize_string(k), normalize_string(v))
            for k, v in pred_pairs
        }
        total_values += 1
        match = exp_pairs_normalized == pred_pairs_normalized
        if match:
            values_matched += 1
        value_details.append({
            'field': 'key_value_pairs',
            'expected': str(exp_pairs) if exp_pairs else '',
            'predicted': str(pred_pairs) if pred_pairs else '',
            'match': match
        })
    
    # Compare enumerations
    exp_enums = set([normalize_string(v) for v in expected_values.get('enumerations', [])])
    pred_enums = set([normalize_string(v) for v in predicted_values.get('enumerations', [])])
    if exp_enums or pred_enums:
        total_values += 1
        match = exp_enums == pred_enums
        if match:
            values_matched += 1
        value_details.append({
            'field': 'enumerations',
            'expected': ', '.join(sorted(exp_enums)) if exp_enums else '',
            'predicted': ', '.join(sorted(pred_enums)) if pred_enums else '',
            'match': match
        })
    
    return {
        'total_values': total_values,
        'values_matched': values_matched,
        'value_details': value_details
    }


def evaluate_annotation(
    expected: str,
    predicted: str,
    note_id: Optional[str] = None,
    prompt_type: Optional[str] = None
) -> Dict:
    """
    Comprehensive evaluation of LLM output against expected annotation.
    
    Args:
        expected: Expected annotation string
        predicted: Predicted/LLM output string
        note_id: Optional note ID for tracking
        prompt_type: Optional prompt type for tracking
    
    Returns:
        Dictionary with evaluation results
    """
    # Basic exact match
    is_exact_match = exact_match(expected, predicted)
    
    # Cosine similarity
    similarity = cosine_similarity_score(expected, predicted)
    
    # Per-value extraction and comparison
    expected_values = extract_structured_values(expected)
    predicted_values = extract_structured_values(predicted)
    value_comparison = compare_values(expected_values, predicted_values)
    
    # Consider high similarity as match (as in FBK example)
    # They consider cosine >= 0.8 as exact match
    is_high_similarity = similarity >= 0.8
    
    # Overall match: exact match OR high similarity
    overall_match = is_exact_match or is_high_similarity
    
    result = {
        'note_id': note_id,
        'prompt_type': prompt_type,
        'exact_match': is_exact_match,
        'similarity_score': round(similarity, 4),
        'high_similarity': is_high_similarity,
        'overall_match': overall_match,
        'expected_annotation': expected,
        'predicted_annotation': predicted,
        'total_values': value_comparison['total_values'],
        'values_matched': value_comparison['values_matched'],
        'value_details': value_comparison['value_details']
    }
    
    # Calculate value match rate if there are values
    if value_comparison['total_values'] > 0:
        result['value_match_rate'] = round(
            value_comparison['values_matched'] / value_comparison['total_values'],
            4
        )
    else:
        result['value_match_rate'] = None
    
    return result


def batch_evaluate(
    evaluations: List[Dict]
) -> Dict:
    """
    Aggregate evaluation results across multiple comparisons.

    Args:
        evaluations: List of evaluation result dictionaries

    Returns:
        Aggregated statistics
    """
    if not evaluations:
        return {
            'total': 0,
            'exact_matches': 0,
            'high_similarity_matches': 0,
            'overall_matches': 0,
            'avg_similarity': 0.0,
            'avg_value_match_rate': 0.0
        }

    total = len(evaluations)
    exact_matches = sum(1 for e in evaluations if e.get('exact_match', False))
    high_similarity = sum(1 for e in evaluations if e.get('high_similarity', False))
    overall_matches = sum(1 for e in evaluations if e.get('overall_match', False))

    similarities = [e.get('similarity_score', 0.0) for e in evaluations]
    avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0

    value_match_rates = [
        e.get('value_match_rate', 0.0)
        for e in evaluations
        if e.get('value_match_rate') is not None
    ]
    avg_value_match_rate = (
        sum(value_match_rates) / len(value_match_rates)
        if value_match_rates else None
    )

    return {
        'total': total,
        'exact_matches': exact_matches,
        'exact_match_rate': round(exact_matches / total, 4) if total > 0 else 0.0,
        'high_similarity_matches': high_similarity,
        'high_similarity_rate': round(high_similarity / total, 4) if total > 0 else 0.0,
        'overall_matches': overall_matches,
        'overall_match_rate': round(overall_matches / total, 4) if total > 0 else 0.0,
        'avg_similarity': round(avg_similarity, 4),
        'avg_value_match_rate': round(avg_value_match_rate, 4) if avg_value_match_rate is not None else None
    }


# ============================================================================
# TEMPLATE-AWARE PER-VALUE EVALUATION
# ============================================================================

def extract_template_placeholders(template: str) -> List[Dict]:
    """
    Extract placeholder definitions from a template string.

    Placeholders are in formats like:
    - [provide date], [put date] -> date type
    - [complete/incomplete], [select intent] -> categorical type
    - [select regimen], [value] -> text type

    Args:
        template: Template string with placeholders

    Returns:
        List of placeholder definitions with type info
    """
    # Find all bracketed placeholders
    placeholder_pattern = r'\[([^\]]+)\]'
    matches = re.finditer(placeholder_pattern, template)

    placeholders = []
    for match in matches:
        placeholder_text = match.group(0)  # Full match including brackets
        placeholder_content = match.group(1)  # Content inside brackets

        # Determine placeholder type
        content_lower = placeholder_content.lower()

        if 'date' in content_lower:
            placeholder_type = 'date'
        elif '/' in placeholder_content:
            # Contains options like "complete/incomplete"
            placeholder_type = 'categorical'
            # Extract options
            options = [opt.strip() for opt in placeholder_content.split('/')]
        elif content_lower.startswith('select'):
            placeholder_type = 'categorical'
        elif content_lower in ['value', 'result']:
            placeholder_type = 'text'
        else:
            placeholder_type = 'text'

        placeholders.append({
            'placeholder': placeholder_text,
            'content': placeholder_content,
            'type': placeholder_type,
            'position': match.start()
        })

    return placeholders


def normalize_date(date_str: str) -> Optional[str]:
    """
    Normalize a date string to a standard format for comparison.

    Handles formats like:
    - DD/MM/YYYY, D/M/YYYY
    - YYYY-MM-DD
    - DD-MM-YYYY

    Args:
        date_str: Input date string

    Returns:
        Normalized date string (YYYY-MM-DD) or None if not parseable
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # Try DD/MM/YYYY or D/M/YYYY format
    match = re.match(r'^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$', date_str)
    if match:
        day, month, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    # Try YYYY-MM-DD format
    match = re.match(r'^(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})$', date_str)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    return None


def is_placeholder_value(value: str) -> bool:
    """
    Check if a value is a placeholder (not filled in).

    Args:
        value: Value to check

    Returns:
        True if value is a placeholder indicator
    """
    if not value:
        return True

    value_lower = value.lower().strip()

    # Check for bracketed placeholders
    if re.match(r'^\[.*\]$', value):
        return True

    # Check for common placeholder patterns
    placeholder_patterns = [
        r'^(provide|put|select|enter)\s+',
        r'^not\s+(specified|available|mentioned|found)$',
        r'^unknown$',
        r'^n/a$',
        r'^none$',
    ]

    for pattern in placeholder_patterns:
        if re.match(pattern, value_lower):
            return True

    return False


def extract_value_at_position(text: str, template: str, placeholder: Dict, all_placeholders: List[Dict]) -> Optional[str]:
    """
    Extract the value from text that corresponds to a template placeholder.

    Uses multiple strategies to locate the value:
    1. Build a full template regex with all placeholders
    2. Use surrounding context for targeted extraction
    3. Fall back to simpler patterns

    Args:
        text: Annotation text to extract from
        template: Original template with placeholders
        placeholder: Placeholder definition to extract
        all_placeholders: All placeholders in template (for context)

    Returns:
        Extracted value or None if not found
    """
    placeholder_text = placeholder['placeholder']

    # Strategy 1: Build full template regex
    # Sort placeholders by position for pattern building
    sorted_placeholders = sorted(all_placeholders, key=lambda x: x['position'])

    # Build pattern from template, replacing each placeholder with appropriate capture/non-capture group
    pattern_parts = []
    last_end = 0

    for i, ph in enumerate(sorted_placeholders):
        # Add escaped literal text before this placeholder
        literal_text = template[last_end:ph['position']]
        if literal_text:
            pattern_parts.append(re.escape(literal_text))

        # Determine what comes after this placeholder (to know when to stop matching)
        next_literal_start = ph['position'] + len(ph['placeholder'])
        if i + 1 < len(sorted_placeholders):
            # There's another placeholder after this one
            next_ph = sorted_placeholders[i + 1]
            after_text = template[next_literal_start:next_ph['position']]
        else:
            # This is the last placeholder
            after_text = template[next_literal_start:]

        # Get the first significant character(s) after placeholder for non-greedy matching
        after_char = after_text.lstrip()[:2] if after_text.strip() else ''

        # Add capture or non-capture group for placeholder
        if ph['placeholder'] == placeholder_text:
            # This is the one we want to capture
            if ph['type'] == 'date':
                pattern_parts.append(r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}[/\-]\d{1,2}[/\-]\d{1,2}|\[[^\]]+\])')
            elif after_char.startswith('('):
                # Value before parenthesis - capture until open paren
                pattern_parts.append(r'([^(]+|\[[^\]]+\])')
            elif after_char.startswith(')'):
                # Value inside parenthesis - capture until close paren
                pattern_parts.append(r'([^)]+|\[[^\]]+\])')
            elif after_char.startswith('.'):
                # Value before period - capture until period
                pattern_parts.append(r'([^.]+|\[[^\]]+\])')
            else:
                # General text - flexible capture
                pattern_parts.append(r'([^\n]+?|\[[^\]]+\])')
        else:
            # Non-capturing group for other placeholders
            if ph['type'] == 'date':
                pattern_parts.append(r'(?:\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}[/\-]\d{1,2}[/\-]\d{1,2}|\[[^\]]+\])')
            elif after_char.startswith('('):
                pattern_parts.append(r'(?:[^(]+|\[[^\]]+\])')
            elif after_char.startswith(')'):
                pattern_parts.append(r'(?:[^)]+|\[[^\]]+\])')
            elif after_char.startswith('.'):
                pattern_parts.append(r'(?:[^.]+|\[[^\]]+\])')
            else:
                pattern_parts.append(r'(?:[^\n]+?|\[[^\]]+\])')

        last_end = ph['position'] + len(ph['placeholder'])

    # Add remaining literal text
    if last_end < len(template):
        pattern_parts.append(re.escape(template[last_end:]))

    full_pattern = ''.join(pattern_parts)

    try:
        match = re.search(full_pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    except re.error:
        pass  # Fall through to alternative strategies

    # Strategy 2: Context-based extraction
    ph_pos = placeholder['position']
    ph_len = len(placeholder_text)

    # Get immediate context (words before and after)
    context_before = template[max(0, ph_pos - 50):ph_pos]
    context_after = template[ph_pos + ph_len:min(len(template), ph_pos + ph_len + 50)]

    # Remove other placeholders from context
    context_before = re.sub(r'\[[^\]]+\]', '', context_before).strip()
    context_after = re.sub(r'\[[^\]]+\]', '', context_after).strip()

    # Get last few words before and first few words after
    before_words = context_before.split()[-3:] if context_before else []
    after_words = context_after.split()[:3] if context_after else []

    before_pattern = r'\s+'.join(re.escape(w) for w in before_words) if before_words else ''
    after_pattern = r'\s+'.join(re.escape(w) for w in after_words) if after_words else ''

    # Build capture pattern based on type
    if placeholder['type'] == 'date':
        capture = r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}[/\-]\d{1,2}[/\-]\d{1,2}|\[[^\]]+\])'
    elif placeholder['type'] == 'categorical':
        capture = r'([a-zA-Z][a-zA-Z0-9\s\-]*?|\[[^\]]+\])'
    else:
        capture = r'(.+?)'

    # Try with both before and after context
    if before_pattern and after_pattern:
        pattern = before_pattern + r'\s+' + capture + r'\s+' + after_pattern
        try:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        except re.error:
            pass

    # Try with just before context
    if before_pattern:
        pattern = before_pattern + r'\s+' + capture
        try:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                # Clean up - remove trailing context words
                if after_words:
                    for word in after_words:
                        if value.lower().endswith(' ' + word.lower()):
                            value = value[:-len(word)-1].strip()
                return value
        except re.error:
            pass

    # Strategy 3: For date types, just find dates in text
    if placeholder['type'] == 'date':
        dates = extract_dates(text)
        if dates:
            # Return the first date found
            return dates[0]

    return None


def compare_field_values(
    expected_value: str,
    predicted_value: str,
    field_type: str,
    expected_annotation_empty: bool = False
) -> Dict:
    """
    Compare two values with type-appropriate matching.

    Args:
        expected_value: Expected value from ground truth
        predicted_value: Predicted value from LLM
        field_type: Type of field ('date', 'categorical', 'text')
        expected_annotation_empty: True if the entire expected annotation was empty/missing
                                   (meaning no annotation was expected at all)

    Returns:
        Comparison result dictionary
    """
    # Check if either value is a placeholder
    expected_is_placeholder = is_placeholder_value(expected_value)
    predicted_is_placeholder = is_placeholder_value(predicted_value)

    result = {
        'expected': expected_value,
        'predicted': predicted_value,
        'field_type': field_type,
        'match': False,
        'match_method': 'none',
        'similarity': 0.0,
        'expected_is_placeholder': expected_is_placeholder,
        'predicted_is_placeholder': predicted_is_placeholder,
    }

    # Special case: Expected annotation was completely empty (no annotation expected)
    # If model predicted any value, it's a FALSE POSITIVE
    if expected_annotation_empty:
        if predicted_is_placeholder or not predicted_value:
            # Both empty/placeholder - correct (no annotation expected, none provided)
            result['match'] = True
            result['match_method'] = 'both_empty'
            result['similarity'] = 1.0
            result['note'] = 'No annotation expected, none provided'
        else:
            # Model predicted a value when none was expected - FALSE POSITIVE
            result['match'] = False
            result['match_method'] = 'false_positive'
            result['similarity'] = 0.0
            result['note'] = 'Value predicted but no annotation was expected'
        return result

    # Case 1: Both are placeholders -> match (both missing)
    if expected_is_placeholder and predicted_is_placeholder:
        result['match'] = True
        result['match_method'] = 'both_placeholder'
        result['similarity'] = 1.0
        return result

    # Case 2: Expected is placeholder, predicted has value -> successful extraction
    # This only applies when expected annotation HAD content with a placeholder
    if expected_is_placeholder and not predicted_is_placeholder:
        result['match'] = True
        result['match_method'] = 'extraction_success'
        result['similarity'] = 1.0
        result['note'] = 'Value extracted where expected had placeholder'
        return result

    # Case 3: Expected has value, predicted is placeholder -> failed extraction
    if not expected_is_placeholder and predicted_is_placeholder:
        result['match'] = False
        result['match_method'] = 'extraction_failed'
        result['similarity'] = 0.0
        return result

    # Case 4: Both have values -> compare based on type
    if field_type == 'date':
        # Normalize dates for comparison
        exp_normalized = normalize_date(expected_value)
        pred_normalized = normalize_date(predicted_value)

        if exp_normalized and pred_normalized:
            if exp_normalized == pred_normalized:
                result['match'] = True
                result['match_method'] = 'date_normalized'
                result['similarity'] = 1.0
            else:
                result['match'] = False
                result['match_method'] = 'date_mismatch'
                result['similarity'] = 0.0
        else:
            # Fallback to exact match if normalization failed
            if exact_match(expected_value, predicted_value):
                result['match'] = True
                result['match_method'] = 'exact'
                result['similarity'] = 1.0
            else:
                result['match'] = False
                result['match_method'] = 'date_format_error'
                result['similarity'] = cosine_similarity_score(expected_value, predicted_value)

    elif field_type == 'categorical':
        # Exact match for categorical values (case-insensitive)
        if exact_match(expected_value, predicted_value):
            result['match'] = True
            result['match_method'] = 'exact'
            result['similarity'] = 1.0
        else:
            # Check for semantic equivalence (e.g., "complete" vs "completely")
            exp_norm = normalize_string(expected_value)
            pred_norm = normalize_string(predicted_value)

            # Check for minor suffix/prefix variations (but not antonyms like complete/incomplete)
            # Only allow containment if lengths are similar (within 3 chars)
            len_diff = abs(len(exp_norm) - len(pred_norm))
            is_similar_length = len_diff <= 3

            # Avoid matching antonyms like "complete" in "incomplete"
            # Check for common negation prefixes
            negation_prefixes = ['in', 'un', 'non', 'dis', 'im', 'ir', 'il']
            has_negation = any(
                (pred_norm.startswith(prefix) and exp_norm == pred_norm[len(prefix):]) or
                (exp_norm.startswith(prefix) and pred_norm == exp_norm[len(prefix):])
                for prefix in negation_prefixes
            )

            if is_similar_length and not has_negation and (exp_norm in pred_norm or pred_norm in exp_norm):
                result['match'] = True
                result['match_method'] = 'semantic'
                result['similarity'] = 0.9
            else:
                result['match'] = False
                result['match_method'] = 'mismatch'
                result['similarity'] = cosine_similarity_score(expected_value, predicted_value)

    else:  # text type
        # Use flexible matching for text
        if exact_match(expected_value, predicted_value):
            result['match'] = True
            result['match_method'] = 'exact'
            result['similarity'] = 1.0
        else:
            similarity = cosine_similarity_score(expected_value, predicted_value)
            result['similarity'] = round(similarity, 4)
            if similarity >= 0.8:
                result['match'] = True
                result['match_method'] = 'high_similarity'
            else:
                result['match'] = False
                result['match_method'] = 'low_similarity'

    return result


def extract_values_from_annotation(annotation: str, template_format: str) -> Dict[str, str]:
    """
    Extract individual field values from an annotation using the template format.

    Args:
        annotation: The annotation text to extract from
        template_format: The output format template (e.g., "Re-excision was performed on [provide date]...")

    Returns:
        Dictionary mapping placeholder names to extracted values
    """
    placeholders = extract_template_placeholders(template_format)

    if not placeholders:
        return {}

    extracted = {}

    for placeholder in placeholders:
        value = extract_value_at_position(annotation, template_format, placeholder, placeholders)
        if value:
            extracted[placeholder['content']] = value
        else:
            # Try alternative extraction methods
            # 1. Check if the placeholder itself appears in annotation
            if placeholder['placeholder'] in annotation:
                extracted[placeholder['content']] = placeholder['placeholder']
            else:
                extracted[placeholder['content']] = None

    return extracted


def evaluate_per_field(
    expected: str,
    predicted: str,
    template_format: str,
    note_id: Optional[str] = None,
    prompt_type: Optional[str] = None
) -> Dict:
    """
    Perform field-level evaluation of annotations using template-aware extraction.

    This evaluates each placeholder field independently and provides granular feedback.

    Args:
        expected: Expected annotation string
        predicted: Predicted/LLM output string
        template_format: The output format template with placeholders
        note_id: Optional note ID for tracking
        prompt_type: Optional prompt type for tracking

    Returns:
        Dictionary with field-level evaluation results
    """
    # Extract placeholders from template
    placeholders = extract_template_placeholders(template_format)

    if not placeholders:
        # No placeholders found - fall back to standard evaluation
        return {
            'field_evaluation_available': False,
            'reason': 'No placeholders found in template format',
            'field_results': []
        }

    # Check if expected annotation is empty/missing entirely
    # This is different from having content with placeholders
    expected_is_empty = not expected or not expected.strip() or is_placeholder_value(expected.strip())

    # Extract values from both expected and predicted
    expected_values = extract_values_from_annotation(expected, template_format)
    predicted_values = extract_values_from_annotation(predicted, template_format)

    # Compare each field
    field_results = []
    fields_matched = 0
    total_fields = len(placeholders)

    for placeholder in placeholders:
        field_name = placeholder['content']
        field_type = placeholder['type']

        exp_value = expected_values.get(field_name, '')
        pred_value = predicted_values.get(field_name, '')

        # Handle None values
        exp_value = exp_value if exp_value else ''
        pred_value = pred_value if pred_value else ''

        comparison = compare_field_values(
            exp_value, pred_value, field_type,
            expected_annotation_empty=expected_is_empty
        )

        field_result = {
            'field_name': field_name,
            'placeholder': placeholder['placeholder'],
            'field_type': field_type,
            'expected': exp_value,
            'predicted': pred_value,
            'match': comparison['match'],
            'match_method': comparison['match_method'],
            'similarity': comparison['similarity'],
        }

        if 'note' in comparison:
            field_result['note'] = comparison['note']

        field_results.append(field_result)

        if comparison['match']:
            fields_matched += 1

    # Calculate overall field match rate
    field_match_rate = fields_matched / total_fields if total_fields > 0 else 0.0

    # Determine overall field match (all fields must match)
    overall_field_match = fields_matched == total_fields

    return {
        'field_evaluation_available': True,
        'note_id': note_id,
        'prompt_type': prompt_type,
        'template_format': template_format,
        'total_fields': total_fields,
        'fields_matched': fields_matched,
        'field_match_rate': round(field_match_rate, 4),
        'overall_field_match': overall_field_match,
        'field_results': field_results
    }


def merge_dates_from_template_and_extracted(
    annotation: str,
    template_dates: List[str],
    extracted_dates: List[str]
) -> List[str]:
    """
    Merge dates from template placeholders and auto-extracted dates.

    When a template has date placeholders that the LLM fills in, we need to
    consider both the dates from the template structure and any additional
    dates that were extracted from the text.

    Args:
        annotation: The annotation text
        template_dates: Dates extracted from template placeholders
        extracted_dates: Dates auto-extracted from text

    Returns:
        Merged list of unique dates (normalized)
    """
    all_dates = set()

    # Add template dates
    for date in template_dates:
        if date and not is_placeholder_value(date):
            normalized = normalize_date(date)
            if normalized:
                all_dates.add(normalized)
            else:
                all_dates.add(date)  # Keep original if can't normalize

    # Add extracted dates
    for date in extracted_dates:
        if date and not is_placeholder_value(date):
            normalized = normalize_date(date)
            if normalized:
                all_dates.add(normalized)
            else:
                all_dates.add(date)

    return list(all_dates)

