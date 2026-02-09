"""
Date Evaluation Module

Extracts and evaluates date predictions from LLM annotations.
Compares expected dates vs predicted dates with various matching strategies.
"""

import re
import json
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from pathlib import Path

from evaluation_engine import extract_dates


def normalize_date(date_str: str) -> Optional[datetime]:
    """
    Normalize a date string to a datetime object.
    Supports multiple date formats.
    
    Args:
        date_str: Date string in various formats
    
    Returns:
        datetime object or None if parsing fails
    """
    if not date_str or not isinstance(date_str, str):
        return None
    
    date_str = date_str.strip()
    
    # Common date formats
    formats = [
        '%d/%m/%Y',      # DD/MM/YYYY
        '%Y-%m-%d',      # YYYY-MM-DD
        '%d-%m-%Y',      # DD-MM-YYYY
        '%m/%d/%Y',      # MM/DD/YYYY (US format)
        '%Y/%m/%d',      # YYYY/MM/DD
        '%d.%m.%Y',      # DD.MM.YYYY
        '%Y.%m.%d',      # YYYY.MM.DD
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    # Try to extract year-month-day from various patterns
    year_match = re.search(r'(\d{4})', date_str)
    month_match = re.search(r'(\d{1,2})', date_str)
    
    if year_match:
        year = int(year_match.group(1))
        # Try to find month and day
        parts = re.findall(r'\d{1,2}', date_str)
        if len(parts) >= 2:
            try:
                month = int(parts[0])
                day = int(parts[1])
                if 1 <= month <= 12 and 1 <= day <= 31:
                    return datetime(year, month, day)
            except (ValueError, IndexError):
                pass
        # If only year found, return first day of year
        if 1900 <= year <= 2100:
            return datetime(year, 1, 1)
    
    return None


def compare_dates(expected_dates: List[str], predicted_dates: List[str]) -> Dict:
    """
    Compare expected and predicted dates.
    
    Args:
        expected_dates: List of expected date strings
        predicted_dates: List of predicted date strings
    
    Returns:
        Dictionary with comparison results
    """
    # Normalize dates
    exp_normalized = [normalize_date(d) for d in expected_dates if d]
    pred_normalized = [normalize_date(d) for d in predicted_dates if d]
    
    # Remove None values
    exp_normalized = [d for d in exp_normalized if d is not None]
    pred_normalized = [d for d in pred_normalized if d is not None]
    
    # Exact match (same dates)
    exp_set = set(exp_normalized)
    pred_set = set(pred_normalized)
    exact_matches = exp_set & pred_set
    
    # Partial matches (same year-month, different day)
    partial_matches = set()
    for exp_d in exp_set:
        for pred_d in pred_set:
            if exp_d.year == pred_d.year and exp_d.month == pred_d.month:
                partial_matches.add(exp_d)
                break
    
    # Year-only matches
    year_matches = set()
    for exp_d in exp_set:
        for pred_d in pred_set:
            if exp_d.year == pred_d.year:
                year_matches.add(exp_d)
                break
    
    # Calculate metrics
    total_expected = len(exp_normalized)
    total_predicted = len(pred_normalized)
    
    exact_match_count = len(exact_matches)
    partial_match_count = len(partial_matches - exact_matches)
    year_match_count = len(year_matches - partial_matches - exact_matches)
    
    # Precision: how many predicted dates are correct
    precision = exact_match_count / total_predicted if total_predicted > 0 else 0.0
    
    # Recall: how many expected dates were found
    recall = exact_match_count / total_expected if total_expected > 0 else 0.0
    
    # F1 score
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {
        'expected_dates': expected_dates,
        'predicted_dates': predicted_dates,
        'expected_count': total_expected,
        'predicted_count': total_predicted,
        'exact_matches': exact_match_count,
        'partial_matches': partial_match_count,
        'year_matches': year_match_count,
        'exact_match_dates': sorted([d.strftime('%Y-%m-%d') for d in exact_matches]),
        'precision': round(precision, 4),
        'recall': round(recall, 4),
        'f1_score': round(f1, 4),
        'date_match': exact_match_count > 0 or (total_expected == 0 and total_predicted == 0),
        'date_match_type': 'exact' if exact_match_count > 0 else ('partial' if partial_match_count > 0 else ('year' if year_match_count > 0 else 'none'))
    }


def evaluate_dates(results_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    """
    Evaluate date extraction from evaluation results.
    
    Args:
        results_df: DataFrame with evaluation results (from evaluate_llm_int_prompts.py)
    
    Returns:
        Tuple of (date_evaluation_df, date_summary_stats)
    """
    date_results = []
    
    for _, row in results_df.iterrows():
        expected_annotation = str(row.get('expected_annotation', ''))
        predicted_annotation = str(row.get('predicted_annotation', ''))
        llm_output = str(row.get('llm_output', ''))
        
        # Extract dates from annotations
        expected_dates = extract_dates(expected_annotation)
        predicted_dates = extract_dates(predicted_annotation)
        
        # Also check llm_output if different from predicted_annotation
        if llm_output and llm_output != predicted_annotation:
            llm_dates = extract_dates(llm_output)
            if llm_dates:
                predicted_dates = list(set(predicted_dates + llm_dates))
        
        # Compare dates
        comparison = compare_dates(expected_dates, predicted_dates)
        
        # Create result row
        date_result = {
            'note_id': row.get('note_id', ''),
            'p_id': row.get('p_id', ''),
            'prompt_type': row.get('prompt_type', ''),
            'report_type': row.get('report_type', ''),
            'expected_dates': ', '.join(expected_dates) if expected_dates else '',
            'predicted_dates': ', '.join(predicted_dates) if predicted_dates else '',
            'expected_count': comparison['expected_count'],
            'predicted_count': comparison['predicted_count'],
            'exact_matches': comparison['exact_matches'],
            'partial_matches': comparison['partial_matches'],
            'year_matches': comparison['year_matches'],
            'date_match': comparison['date_match'],
            'date_match_type': comparison['date_match_type'],
            'date_precision': comparison['precision'],
            'date_recall': comparison['recall'],
            'date_f1_score': comparison['f1_score'],
            'exact_match_dates': ', '.join(comparison['exact_match_dates']) if comparison['exact_match_dates'] else ''
        }
        
        date_results.append(date_result)
    
    date_df = pd.DataFrame(date_results)
    
    # Calculate summary statistics
    total_rows = len(date_df)
    rows_with_expected_dates = len(date_df[date_df['expected_count'] > 0])
    rows_with_predicted_dates = len(date_df[date_df['predicted_count'] > 0])
    rows_with_exact_match = len(date_df[date_df['date_match'] == True])
    
    # Per-prompt-type statistics
    prompt_type_stats = {}
    for prompt_type in date_df['prompt_type'].unique():
        prompt_df = date_df[date_df['prompt_type'] == prompt_type]
        prompt_rows_with_dates = len(prompt_df[prompt_df['expected_count'] > 0])
        prompt_exact_matches = len(prompt_df[prompt_df['date_match'] == True])
        
        prompt_type_stats[prompt_type] = {
            'total_evaluations': len(prompt_df),
            'rows_with_expected_dates': prompt_rows_with_dates,
            'rows_with_exact_match': prompt_exact_matches,
            'date_accuracy': round(prompt_exact_matches / prompt_rows_with_dates, 4) if prompt_rows_with_dates > 0 else 0.0,
            'avg_precision': round(prompt_df['date_precision'].mean(), 4) if len(prompt_df) > 0 else 0.0,
            'avg_recall': round(prompt_df['date_recall'].mean(), 4) if len(prompt_df) > 0 else 0.0,
            'avg_f1': round(prompt_df['date_f1_score'].mean(), 4) if len(prompt_df) > 0 else 0.0
        }
    
    # Overall statistics
    overall_avg_precision = date_df['date_precision'].mean() if len(date_df) > 0 else 0.0
    overall_avg_recall = date_df['date_recall'].mean() if len(date_df) > 0 else 0.0
    overall_avg_f1 = date_df['date_f1_score'].mean() if len(date_df) > 0 else 0.0
    
    summary_stats = {
        'total_evaluations': total_rows,
        'rows_with_expected_dates': rows_with_expected_dates,
        'rows_with_predicted_dates': rows_with_predicted_dates,
        'rows_with_exact_match': rows_with_exact_match,
        'overall_date_accuracy': round(rows_with_exact_match / rows_with_expected_dates, 4) if rows_with_expected_dates > 0 else 0.0,
        'overall_avg_precision': round(overall_avg_precision, 4),
        'overall_avg_recall': round(overall_avg_recall, 4),
        'overall_avg_f1': round(overall_avg_f1, 4),
        'per_prompt_type': prompt_type_stats
    }
    
    return date_df, summary_stats
