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


def normalize_string(text: str) -> str:
    """
    Normalize string for comparison: Unicode NFKC, lowercase, strip.
    
    Args:
        text: Input string (or any type that can be converted to string)
    
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
    return normalized


def exact_match(expected: str, predicted: str) -> bool:
    """
    Check if two strings match exactly after normalization.
    
    Args:
        expected: Expected annotation string
        predicted: Predicted/LLM output string
    
    Returns:
        True if strings match exactly after normalization
    """
    norm_expected = normalize_string(expected)
    norm_predicted = normalize_string(predicted)
    
    # Handle empty cases
    if not norm_expected and not norm_predicted:
        return True  # Both empty = match
    if not norm_expected or not norm_predicted:
        return False  # One empty, one not = mismatch
    
    return norm_expected == norm_predicted


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

