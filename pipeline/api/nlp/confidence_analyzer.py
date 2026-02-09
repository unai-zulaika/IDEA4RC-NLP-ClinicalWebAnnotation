"""
Confidence Analyzer Module

Analyzes logprobs from VLLM to calculate confidence scores and determine
if predictions should be rejected as "no outcome" when confidence is low.
"""

from typing import Dict, List, Optional, Tuple
import statistics


def calculate_confidence_from_logprobs(
    logprobs_data: Optional[Dict],
    prompt_type: Optional[str] = None,
    method: str = "average"
) -> Optional[float]:
    """
    Calculate confidence score from VLLM logprobs data.
    
    Args:
        logprobs_data: Logprobs data from VLLM API response
        prompt_type: Optional prompt type (for future per-type handling)
        method: Method to calculate confidence ("average", "min", "first")
    
    Returns:
        Confidence score (logprob value, typically -10 to 0, higher = more confident)
        Returns None if logprobs_data is None or invalid
    """
    if logprobs_data is None:
        return None
    
    # Extract token_logprobs from VLLM response
    token_logprobs = logprobs_data.get("token_logprobs")
    if not token_logprobs or len(token_logprobs) == 0:
        return None
    
    # Filter out None values (some tokens may not have logprobs)
    valid_logprobs = [lp for lp in token_logprobs if lp is not None]
    if len(valid_logprobs) == 0:
        return None
    
    # Calculate confidence based on method
    if method == "average":
        return statistics.mean(valid_logprobs)
    elif method == "min":
        return min(valid_logprobs)
    elif method == "first":
        return valid_logprobs[0]
    else:
        # Default to average
        return statistics.mean(valid_logprobs)


def normalize_confidence_score(
    logprob: float,
    min_logprob: float = -10.0,
    max_logprob: float = 0.0
) -> float:
    """
    Normalize logprob to 0-1 confidence scale.
    
    Args:
        logprob: Raw logprob value
        min_logprob: Minimum expected logprob (default: -10.0)
        max_logprob: Maximum expected logprob (default: 0.0)
    
    Returns:
        Normalized confidence score (0.0 to 1.0)
    """
    if logprob is None:
        return 0.0
    
    # Clamp logprob to expected range
    clamped = max(min_logprob, min(max_logprob, logprob))
    
    # Normalize to 0-1 scale
    normalized = (clamped - min_logprob) / (max_logprob - min_logprob)
    return max(0.0, min(1.0, normalized))


def should_reject_as_no_outcome(
    confidence_score: Optional[float],
    threshold: float,
    prompt_type: Optional[str] = None,
    use_normalized: bool = False
) -> bool:
    """
    Determine if a prediction should be rejected as "no outcome" based on confidence.
    
    Args:
        confidence_score: Confidence score (logprob or normalized 0-1)
        threshold: Threshold value (logprob scale if use_normalized=False, 0-1 if True)
        prompt_type: Optional prompt type (for future per-type thresholds)
        use_normalized: If True, threshold is in 0-1 scale; if False, logprob scale
    
    Returns:
        True if prediction should be rejected (confidence too low)
    """
    if confidence_score is None:
        # If no confidence data available, don't reject (let it through)
        return False
    
    if use_normalized:
        # Normalized scale: lower score = lower confidence
        return confidence_score < threshold
    else:
        # Logprob scale: lower (more negative) = lower confidence
        return confidence_score < threshold


def get_confidence_metrics(logprobs_data: Optional[Dict]) -> Dict[str, Optional[float]]:
    """
    Calculate confidence statistics from logprobs data.
    
    Args:
        logprobs_data: Logprobs data from VLLM API response
    
    Returns:
        Dictionary with min, max, average, and count of logprobs
    """
    if logprobs_data is None:
        return {
            "min_logprob": None,
            "max_logprob": None,
            "avg_logprob": None,
            "count": 0
        }
    
    token_logprobs = logprobs_data.get("token_logprobs")
    if not token_logprobs or len(token_logprobs) == 0:
        return {
            "min_logprob": None,
            "max_logprob": None,
            "avg_logprob": None,
            "count": 0
        }
    
    valid_logprobs = [lp for lp in token_logprobs if lp is not None]
    if len(valid_logprobs) == 0:
        return {
            "min_logprob": None,
            "max_logprob": None,
            "avg_logprob": None,
            "count": 0
        }
    
    return {
        "min_logprob": min(valid_logprobs),
        "max_logprob": max(valid_logprobs),
        "avg_logprob": statistics.mean(valid_logprobs),
        "count": len(valid_logprobs)
    }


def analyze_output_for_placeholders(output_text: str) -> bool:
    """
    Check if output contains placeholder patterns indicating uncertainty.
    
    Args:
        output_text: Generated output text
    
    Returns:
        True if output contains placeholder patterns
    """
    if not output_text:
        return True
    
    import re
    output_lower = output_text.lower()
    
    # Check for placeholder patterns like [select type], [provide date], etc.
    placeholder_pattern = r'\[[^\]]+\]'
    if re.search(placeholder_pattern, output_lower):
        return True
    
    # Check for "unknown" keywords
    unknown_keywords = [
        "unknown", "not applicable", "no information", 
        "not mentioned", "not stated", "unclear"
    ]
    for keyword in unknown_keywords:
        if keyword in output_lower:
            return True
    
    return False

